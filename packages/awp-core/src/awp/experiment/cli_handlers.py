"""CLI handlers for ``awp experiment ...`` and ``awp task ...`` subcommands."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from awp.experiment.disk import (
    append_task_to_order,
    read_experiment_manifest,
    read_task_manifest,
    write_experiment_manifest,
    write_task_manifest,
)
from awp.experiment.paths import experiment_dir, slug_from_prompt, task_dir, task_id_for
from awp.models.experiment import ExperimentManifest
from awp.models.task import InputRole, TaskInput, TaskManifest, TaskMode


# ---------------------------------------------------------------------------
# Store helpers (optional — awp-ui may not be installed)
# ---------------------------------------------------------------------------

def _ui_db_path() -> Path:
    override = os.environ.get("AWP_UI_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".awp" / "awp_ui.db"


async def _with_store(fn):
    """Run *fn(store)* with a live StoreService; return None if awp-ui is absent."""
    try:
        from server.services.store import StoreService  # type: ignore[import]
    except ModuleNotFoundError:
        return None
    store = StoreService(db_path=_ui_db_path())
    await store.init_db()
    try:
        return await fn(store)
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def handle_experiment_command(args: Namespace) -> int:
    cmd = args.experiment_cmd
    if cmd == "create":
        return _exp_create(args.name, args.goal)
    if cmd == "list":
        return _exp_list()
    if cmd == "show":
        return _exp_show(args.experiment_id)
    if cmd == "delete":
        return _exp_delete(args.experiment_id, args.yes)
    if cmd == "purge-legacy":
        return _purge_legacy_experiments(args.yes)
    print(f"unknown experiment subcommand: {cmd}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _exp_create(name: str, goal: str) -> int:
    manifest = ExperimentManifest.new(name=name, goal=goal)
    disk_path = write_experiment_manifest(manifest)

    async def _insert(store):
        await store.create_experiment(
            experiment_id=manifest.experiment_id,
            name=manifest.name,
            goal=manifest.goal,
            base_dir=str(experiment_dir(manifest.experiment_id)),
            created_at=time.time(),
        )

    asyncio.run(_with_store(_insert))
    print(
        json.dumps(
            {
                "experiment_id": manifest.experiment_id,
                "manifest_path": str(disk_path),
            },
            indent=2,
        )
    )
    return 0


def _exp_list() -> int:
    """List experiments.

    Primary source: StoreService (when awp-ui is installed).
    Fallback: scan EXPERIMENTS_ROOT on disk.
    """
    async def _fetch(store):
        return await store.list_experiments()

    rows = asyncio.run(_with_store(_fetch))

    if rows is not None:
        # StoreService returns dicts with key "id"; normalise to "experiment_id"
        # for a consistent CLI contract.
        normalised = []
        for r in rows:
            entry = dict(r)
            if "id" in entry and "experiment_id" not in entry:
                entry["experiment_id"] = entry.pop("id")
            normalised.append(entry)
        print(json.dumps(normalised, indent=2, default=str))
        return 0

    # Fallback: read from disk when awp-ui is not installed.
    from awp.experiment.paths import EXPERIMENTS_ROOT

    results = []
    if EXPERIMENTS_ROOT.exists():
        for child in sorted(EXPERIMENTS_ROOT.iterdir()):
            manifest_path = child / "experiment.json"
            if manifest_path.exists():
                try:
                    m = ExperimentManifest.model_validate_json(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    results.append(
                        {
                            "experiment_id": m.experiment_id,
                            "name": m.name,
                            "goal": m.goal,
                        }
                    )
                except Exception:
                    pass
    print(json.dumps(results, indent=2, default=str))
    return 0


def _exp_show(experiment_id: str) -> int:
    try:
        manifest = read_experiment_manifest(experiment_id)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(manifest.model_dump_json(indent=2))
    return 0


def _exp_delete(experiment_id: str, yes: bool) -> int:
    exp = experiment_dir(experiment_id)
    if not yes:
        resp = input(f"Delete {exp} and all its runs? [y/N] ").strip().lower()
        if resp != "y":
            print("aborted.")
            return 1
    if exp.exists():
        shutil.rmtree(exp)

    async def _del(store):
        await store.delete_experiment(experiment_id)

    asyncio.run(_with_store(_del))
    print(f"deleted {experiment_id}")
    return 0


def _purge_legacy_experiments(yes: bool) -> int:
    """Delete directories without an experiment.json at root + orphan runs rows."""
    from awp.experiment.paths import EXPERIMENTS_ROOT

    root = EXPERIMENTS_ROOT
    if not root.exists():
        print("no experiments root on disk; nothing to purge.")
        return 0

    legacy_dirs = [
        p for p in sorted(root.iterdir())
        if p.is_dir() and not (p / "experiment.json").exists()
    ]

    if not legacy_dirs:
        print("no legacy (flat-layout) directories found.")
        disk_deleted = 0
    else:
        print(f"Found {len(legacy_dirs)} legacy dir(s) under {root}:")
        for p in legacy_dirs:
            print(f"  - {p.name}")
        if not yes:
            resp = input("Delete these directories? [y/N] ").strip().lower()
            if resp != "y":
                print("aborted.")
                return 1
        for p in legacy_dirs:
            shutil.rmtree(p)
        disk_deleted = len(legacy_dirs)

    # Delete orphan runs rows (experiment_id IS NULL)
    async def _purge_db(store):
        await store.db.execute("DELETE FROM runs WHERE experiment_id IS NULL")
        await store.db.commit()
        cur = await store.db.execute("SELECT changes() AS n")
        row = await cur.fetchone()
        return row["n"]

    orphan_rows = asyncio.run(_with_store(_purge_db)) or 0
    print(
        json.dumps({
            "legacy_dirs_deleted": disk_deleted,
            "orphan_runs_rows_deleted": orphan_rows,
        }, indent=2)
    )
    return 0


# ---------------------------------------------------------------------------
# task subcommands
# ---------------------------------------------------------------------------

def handle_task_command(args: Namespace) -> int:
    cmd = args.task_cmd
    if cmd == "create":
        if args.continuation:
            return _task_create_continuation(args)
        return _task_create_seed(args)
    if cmd == "list":
        return _task_list(args.experiment_id)
    if cmd == "show":
        return _task_show(args.task_key)
    if cmd == "delete":
        return _task_delete(args.task_key, args.yes)
    if cmd == "set-best":
        return _task_set_best(args)
    print(f"unknown task subcommand: {cmd}", file=sys.stderr)
    return 2


def _next_task_number(experiment_id: str) -> int:
    manifest = read_experiment_manifest(experiment_id)
    return len(manifest.task_order) + 1


def _task_create_seed(args: Namespace) -> int:
    if args.from_task or args.primary or args.reference:
        print(
            "--from-task/--primary/--reference require --continuation", file=sys.stderr
        )
        return 2
    number = _next_task_number(args.experiment_id)
    slug = slug_from_prompt(args.prompt)
    tid = task_id_for(number, slug)
    manifest = TaskManifest(
        task_id=tid,
        experiment_id=args.experiment_id,
        task_number=number,
        mode=TaskMode.SEED,
        user_prompt=args.prompt,
        user_feedback=None,
        inputs=[],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return _persist_task(args.experiment_id, manifest, slug)


def _persist_task(experiment_id: str, manifest: TaskManifest, slug: str) -> int:
    path = write_task_manifest(experiment_id, manifest)
    append_task_to_order(experiment_id, manifest.task_id)

    async def _insert(store):
        await store.create_task(
            task_id_key=f"{experiment_id}:{manifest.task_id}",
            experiment_id=experiment_id,
            task_number=manifest.task_number,
            slug=slug,
            mode=manifest.mode.value,
            user_prompt=manifest.user_prompt,
            user_feedback=manifest.user_feedback,
            inputs_json=json.dumps(
                [inp.model_dump(mode="json") for inp in manifest.inputs]
            ),
            created_at=time.time(),
        )

    asyncio.run(_with_store(_insert))
    print(
        json.dumps(
            {
                "task_id": manifest.task_id,
                "manifest_path": str(path),
            },
            indent=2,
        )
    )
    return 0


def _task_list(experiment_id: str) -> int:
    async def _fetch(store):
        return await store.list_tasks(experiment_id)

    rows = asyncio.run(_with_store(_fetch)) or []
    print(json.dumps(rows, indent=2, default=str))
    return 0


def _split_key(task_key: str) -> tuple[str, str]:
    if ":" not in task_key:
        raise SystemExit("task key must be <experiment_id>:<task_id>")
    exp_id, tid = task_key.split(":", 1)
    return exp_id, tid


def _task_show(task_key: str) -> int:
    exp_id, tid = _split_key(task_key)
    try:
        manifest = read_task_manifest(exp_id, tid)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(manifest.model_dump_json(indent=2))
    return 0


def _task_delete(task_key: str, yes: bool) -> int:
    exp_id, tid = _split_key(task_key)
    td = task_dir(exp_id, tid)
    if not yes:
        resp = input(f"Delete {td}? [y/N] ").strip().lower()
        if resp != "y":
            return 1
    if td.exists():
        shutil.rmtree(td)

    async def _del(store):
        await store.delete_task(f"{exp_id}:{tid}")

    asyncio.run(_with_store(_del))

    # Remove from task_order
    manifest = read_experiment_manifest(exp_id)
    manifest.task_order = [t for t in manifest.task_order if t != tid]
    write_experiment_manifest(manifest)
    print(f"deleted {task_key}")
    return 0


def _task_set_best(args: Namespace) -> int:
    """Handle `awp task set-best <task_key> [--run ID | --auto]`."""
    exp_id, tid = _split_key(args.task_key)
    td = task_dir(exp_id, tid)
    if not td.exists():
        print(f"task not found: {args.task_key}", file=sys.stderr)
        return 2

    try:
        from awp.outer_loop.best_finaliser import compute_and_update_best
    except ImportError as exc:
        print(f"awp-runtime required: {exc}", file=sys.stderr)
        return 2

    runs_root = td / "seed" / "output"

    if args.run_id:
        # User override: pin a specific run as BEST
        new_run_dir = runs_root / args.run_id
        if not new_run_dir.exists():
            print(f"run not found: {args.run_id}", file=sys.stderr)
            return 2
        result = compute_and_update_best(
            task_dir=td, new_run_dir=new_run_dir, force_override=True,
        )
        if not result.updated:
            print(
                f"BEST not updated: skip_reason={result.skip_reason}",
                file=sys.stderr,
            )
            return 1
        async def _mirror_override(store):
            await store.set_task_best(
                task_id_key=args.task_key, run_id=args.run_id, reason="user_override",
            )
        asyncio.run(_with_store(_mirror_override))
        print(json.dumps({"best_run_id": args.run_id, "reason": "user_override"}))
        return 0

    # --auto: clear any override, reselect based on lowest loss
    manifest_path = td / "BEST" / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    if not runs_root.exists():
        print(f"no runs under {runs_root}", file=sys.stderr)
        return 2
    best_run_id = None
    for run_dir_ in sorted(runs_root.iterdir()):
        if not run_dir_.is_dir():
            continue
        result = compute_and_update_best(task_dir=td, new_run_dir=run_dir_)
        if result.updated:
            best_run_id = run_dir_.name
    if best_run_id is None:
        print("no eligible terminal runs found", file=sys.stderr)
        return 1
    async def _mirror_auto(store):
        await store.set_task_best(
            task_id_key=args.task_key, run_id=best_run_id, reason="auto_loss",
        )
    asyncio.run(_with_store(_mirror_auto))
    print(json.dumps({"best_run_id": best_run_id, "reason": "auto_loss"}))
    return 0


def _task_create_continuation(args: Namespace) -> int:
    if not args.from_task:
        print(
            "continuation task requires at least one --from-task (R37)",
            file=sys.stderr,
        )
        return 2

    inputs: list[TaskInput] = []
    for src in args.from_task:
        parent_dir = task_dir(args.experiment_id, src)
        if not parent_dir.exists():
            print(f"from_task not found: {src}", file=sys.stderr)
            return 2
        best = parent_dir / "BEST"
        if not best.exists():
            print(
                f"from_task {src} has no BEST/ — run it to completion first",
                file=sys.stderr,
            )
            return 2
        bundle = args.primary or "BEST/"
        inputs.append(
            TaskInput(from_task=src, role=InputRole.PRIMARY, bundle=bundle)
        )
        for ref in args.reference:
            inputs.append(
                TaskInput(
                    from_task=src, role=InputRole.REFERENCE, paths=[ref]
                )
            )

    number = _next_task_number(args.experiment_id)
    slug = slug_from_prompt(args.prompt)
    tid = task_id_for(number, slug)
    try:
        manifest = TaskManifest(
            task_id=tid,
            experiment_id=args.experiment_id,
            task_number=number,
            mode=TaskMode.CONTINUATION,
            user_prompt=None,
            user_feedback=args.prompt,
            inputs=inputs,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return _persist_task(args.experiment_id, manifest, slug)


# ---------------------------------------------------------------------------
# Task validation for `awp run --task`
# ---------------------------------------------------------------------------


def validate_task_key_for_run(task_key: str) -> int:
    """Validate --task argument for `awp run`. Returns 0 on OK, non-zero on error."""
    if ":" not in task_key:
        print(
            "--task must be <experiment_id>:<task_id>",
            file=sys.stderr,
        )
        return 2
    exp_id, tid = task_key.split(":", 1)
    if not experiment_dir(exp_id).exists():
        print(f"experiment not found: {exp_id}", file=sys.stderr)
        return 2
    try:
        read_task_manifest(exp_id, tid)
    except FileNotFoundError:
        print(f"task not found: {task_key}", file=sys.stderr)
        return 2
    # NOTE: Plan 3 lifted the "continuation unsupported" gate — continuation
    # dispatch happens in run_task_aware.
    return 0


def run_task_aware(args: Namespace) -> int:
    """Handle `awp run --target <exp>:<task_id>` by delegating to AgentWorkflow."""
    from awp.experiment.paths import experiment_dir as _exp_dir

    exp_id, tid = args.target.split(":", 1)
    td = task_dir(exp_id, tid)
    output_dir = td / "seed"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_task_manifest(exp_id, tid)
    is_continuation = manifest.mode.value == "continuation"

    # Build the continuation prefix if applicable
    manager_prompt_prefix: str | None = None
    if is_continuation:
        try:
            from awp.continuation import (
                load_continuation_bundle,
                render_continuation_prefix,
            )
        except ImportError as exc:  # pragma: no cover
            print(
                f"awp-runtime required for continuation: {exc}",
                file=sys.stderr,
            )
            return 2
        bundle = load_continuation_bundle(
            task_dir=td, experiment_dir=_exp_dir(exp_id),
        )
        manager_prompt_prefix = render_continuation_prefix(bundle)

    if os.environ.get("AWP_RUN_TASK_DRY_RUN") == "1":
        print(json.dumps({
            "output_dir": str(output_dir),
            "target": args.target,
            "mode": manifest.mode.value,
            "has_prefix": manager_prompt_prefix is not None,
        }))
        return 0

    # Capture-only path for tests that want to inspect the AgentWorkflow kwargs
    # without actually running the LLM.
    capture_path = os.environ.get("AWP_CONTINUATION_CAPTURE_ONLY")
    if capture_path:
        # Resolve task_text the same way the real path will
        task_text = manifest.user_feedback if is_continuation else (
            args.task or manifest.user_prompt or "run task"
        )
        model = args.manager_model or args.model or "openai/gpt-5-mini"
        Path(capture_path).write_text(json.dumps({
            "output_dir": str(output_dir),
            "task": task_text,
            "manager_prompt_prefix": manager_prompt_prefix or "",
            "mode": manifest.mode.value,
            "model": model,
        }, indent=2))
        return 0

    try:
        from awp.data.workflow import AgentWorkflow
    except ImportError as exc:  # pragma: no cover
        print(
            f"awp-runtime is required for task-aware runs: {exc}",
            file=sys.stderr,
        )
        return 2

    # For continuation, the Manager's task is the user_feedback;
    # for seed, it's the CLI --task or the stored user_prompt.
    if is_continuation:
        task_text = manifest.user_feedback or ""
    else:
        task_text = args.task or manifest.user_prompt or "run task"

    model = args.manager_model or args.model or "openai/gpt-5-mini"
    worker_model = args.worker_model or "deepseek/deepseek-chat-v3.1"

    workflow_path = Path(args.path)
    inputs: dict = {}
    if workflow_path.is_file():
        inputs["workflow_path"] = str(workflow_path)
    elif workflow_path.is_dir():
        inputs["workflow_dir"] = str(workflow_path)

    wf = AgentWorkflow(
        inputs=inputs,
        task=task_text,
        model=model,
        worker_model=worker_model,
        output_dir=str(output_dir),
        tags=["task", exp_id, tid] + (["continuation"] if is_continuation else []),
        manager_prompt_prefix=manager_prompt_prefix,
    )
    try:
        result = wf.run()
    except Exception as exc:
        print(f"AgentWorkflow.run failed: {exc}", file=sys.stderr)
        result = None

    run_id: str | None = None
    if result is not None:
        run_id = getattr(result, "run_id", None)
        if run_id is None and isinstance(result, dict):
            run_id = result.get("run_id")

    return _post_run_finalise(
        output_dir=output_dir,
        run_id=run_id,
        exp_id=exp_id,
        task_key=args.target,
        task_text=task_text,
        model=model,
    )


def _post_run_finalise(
    output_dir: Path,
    run_id: str | None,
    exp_id: str,
    task_key: str,
    task_text: str,
    model: str,
    run_role: str = "seed",
) -> int:
    """Read the freshly-finished run, register it in awp_ui.db, and update BEST/."""
    # Locate run_dir if run_id not known
    runs_root = output_dir / "output"
    if run_id is None:
        if not runs_root.exists():
            print(f"no run output directory found at {runs_root}", file=sys.stderr)
            return 1
        candidates = sorted(
            (p for p in runs_root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            print(f"no run output found under {runs_root}", file=sys.stderr)
            return 1
        run_dir = candidates[-1]
        run_id = run_dir.name
    else:
        run_dir = runs_root / run_id

    completion_path = run_dir / "run_completion.json"
    if not completion_path.exists():
        print(f"missing run_completion.json at {completion_path}", file=sys.stderr)
        return 1
    completion = json.loads(completion_path.read_text())
    status = completion.get("status", "unknown")

    # Compute loss (skip for non-terminal)
    loss: float | None = None
    if status in ("complete", "partial"):
        try:
            from awp.outer_loop.loss import compute_run_loss
            loss = compute_run_loss(run_dir).total
        except Exception as exc:  # pragma: no cover - defensive
            print(f"compute_run_loss failed: {exc}", file=sys.stderr)

    # Upsert DB row
    async def _upsert(store):
        await store.upsert_run_for_task(
            run_id=run_id,
            experiment_id=exp_id,
            task_id=task_key,
            run_role=run_role,
            loss=loss,
            status=status,
            task=task_text,
            model=model,
        )

    asyncio.run(_with_store(_upsert))

    # Invoke BEST finaliser
    try:
        from awp.outer_loop.best_finaliser import compute_and_update_best
    except ImportError as exc:  # pragma: no cover
        print(f"awp-runtime required: {exc}", file=sys.stderr)
        return 1

    # Compute task_dir: for any run (seed, refine, optimize), walk back to <exp>/tasks/<task>/
    from awp.experiment.paths import experiment_dir as exp_dir_fn, task_dir as task_dir_fn
    task_id = task_key.split(":", 1)[1] if ":" in task_key else task_key
    task_dir_path = task_dir_fn(exp_id, task_id)
    result = compute_and_update_best(task_dir=task_dir_path, new_run_dir=run_dir)

    # Mirror BEST to DB if it changed
    if result.updated:
        async def _set_best(store):
            await store.set_task_best(
                task_id_key=task_key,
                run_id=run_id,
                reason=result.reason,
            )
        asyncio.run(_with_store(_set_best))

    print(
        json.dumps({
            "run_id": run_id,
            "status": status,
            "loss": loss,
            "best_updated": result.updated,
            "best_reason": result.reason,
        }, indent=2)
    )
    return 0


def refine_task_aware(args) -> int:
    """Handle `awp refine --target <exp>:<task>`."""
    from awp.experiment.paths import experiment_dir as _exp_dir
    from awp.experiment.paths import task_dir as _task_dir

    if ":" not in args.target:
        print("--target must be <experiment_id>:<task_id>", file=sys.stderr)
        return 2
    exp_id, tid = args.target.split(":", 1)
    if not _exp_dir(exp_id).exists():
        print(f"experiment not found: {exp_id}", file=sys.stderr)
        return 2
    td = _task_dir(exp_id, tid)
    if not td.exists():
        print(f"task not found: {args.target}", file=sys.stderr)
        return 2

    best_manifest = td / "BEST" / "manifest.json"
    if not best_manifest.exists():
        print(
            f"task {args.target} has no BEST/ — run it to completion first "
            f"(refinement requires a completed run to refine)",
            file=sys.stderr,
        )
        return 2
    manifest = json.loads(best_manifest.read_text())
    seed_run_dir = Path(manifest.get("winner_source", ""))
    if not seed_run_dir.exists():
        print(
            f"winner_source missing on disk: {seed_run_dir}", file=sys.stderr,
        )
        return 2

    import time as _time
    session_ts = _time.strftime("%Y%m%d_%H%M%S")
    iterations_root = td / "refinements" / f"session_{session_ts}"

    if os.environ.get("AWP_REFINE_TARGET_DRY_RUN") == "1":
        print(json.dumps({
            "target": args.target,
            "seed_run_dir": str(seed_run_dir),
            "iterations_root": str(iterations_root),
        }))
        return 0

    try:
        from awp.refinement.loop import RefinementLoop
    except ImportError as exc:
        print(f"awp-runtime required: {exc}", file=sys.stderr)
        return 2

    iterations_root.mkdir(parents=True, exist_ok=True)
    loop = RefinementLoop(
        seed_run_dir=seed_run_dir,
        iterations_root=iterations_root,
        model=getattr(args, "model", None),
        worker_model=getattr(args, "worker_model", None),
        session_sidecar_dir=iterations_root,
    )
    n_iters = getattr(args, "iterations", None) or 3
    result = loop.run(iterations=n_iters)

    # Post-run hook for EACH iteration's winning run(s); simplest:
    # finalise all iter_k run_dirs the loop produced, so BEST for the
    # task considers refinement candidates too.
    for iter_dir in sorted(iterations_root.glob("iter_*")):
        for run_dir in (iter_dir / "output").glob("*"):
            if not run_dir.is_dir():
                continue
            _post_run_finalise(
                output_dir=iter_dir,
                run_id=run_dir.name,
                exp_id=exp_id,
                task_key=args.target,
                task_text=f"refine iteration",
                model=getattr(args, "model", None) or "openai/gpt-5-mini",
                run_role="refine_iter",
            )
    print(json.dumps({
        "target": args.target,
        "iterations_root": str(iterations_root),
        "session_completed": True,
    }))
    return 0


def optimize_task_aware(args) -> int:
    """Handle `awp optimize --target <exp>:<task> SUITE.yaml`."""
    from awp.experiment.paths import experiment_dir as _exp_dir
    from awp.experiment.paths import task_dir as _task_dir

    if ":" not in args.target:
        print("--target must be <experiment_id>:<task_id>", file=sys.stderr)
        return 2
    exp_id, tid = args.target.split(":", 1)
    exp_path = _exp_dir(exp_id)
    if not exp_path.exists():
        print(f"experiment not found: {exp_id}", file=sys.stderr)
        return 2
    td = _task_dir(exp_id, tid)
    if not td.exists():
        print(f"task not found: {args.target}", file=sys.stderr)
        return 2

    import time as _time
    suite_ts = _time.strftime("%Y%m%d_%H%M%S")
    db_path = exp_path / "outer_loop.db"
    output_dir = td / "optimizations" / f"suite_{suite_ts}"

    if os.environ.get("AWP_OPTIMIZE_TARGET_DRY_RUN") == "1":
        print(json.dumps({
            "target": args.target,
            "db_path": str(db_path),
            "output_dir": str(output_dir),
        }))
        return 0

    # Override args before calling the existing cmd_optimize logic.
    # Because cmd_optimize owns the SuiteRunner instantiation and A2/A3
    # branch selection, we rewrite args.db + args.output_dir and then
    # re-enter cmd_optimize with target cleared (to avoid recursion).
    args.db = str(db_path)
    args.output_dir = str(output_dir)
    args.target = None  # prevent re-entry

    # Lazy import to avoid cyclic
    from awp.cli import cmd_optimize
    return cmd_optimize(args)
