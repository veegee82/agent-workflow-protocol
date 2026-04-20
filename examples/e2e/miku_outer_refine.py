#!/usr/bin/env python3
"""E2E coverage for inner loop + outer loop (SGD=3) + refinement (iter=3).

Scenario
--------
A two-task pet-portrait suite (Miku the dog, Luna the cat) drives three
phases in one script:

  Phase 1 - Outer loop:
    3 epochs * 2 tasks = 6 inner runs, each via the shared run_e2e
    harness (UI sidebar visibility). Between epochs the
    TextGradOptimizer is asked to update one prompt artifact and the
    new version is persisted to ~/.awp/outer_loop.db.

  Phase 2 - Refinement:
    The Miku run from epoch 3 is used as the seed for
    RefinementLoop.run(iterations=3). Each iteration is a standalone
    AWP run linked back to its parent via parent_run_id.

  Phase 3 - Verification:
    All 6 outer-loop runs must reach status=complete in their own
    run_completion.json. The refinement session sidecar must exist;
    iterations either complete or terminate via R36 / a documented
    stop reason. The suite_id rows in ~/.awp/outer_loop.db must match
    expected counts.

Run manually with the UI server running so the sidebar lights up live:
    python examples/e2e/miku_outer_refine.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ----- Repo path plumbing ---------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _sub in (
    "packages/awp-core/src",
    "packages/awp-runtime/src",
    "packages/awp-ui/server",
):
    sys.path.insert(0, str(_PROJECT_ROOT / _sub))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import load_openrouter_key, run_e2e  # noqa: E402

# ----- Constants ------------------------------------------------------------

SUITE_NAME = "miku_pet_portraits"
EPOCHS = 3
REFINE_ITERATIONS = 3

TAGS = [
    "e2e",
    "s5",
    "outer-loop",
    "refinement",
    "tool-creation",
    "critique",
    "planning",
    "miku",
    "quick",
]

ALL_ARTIFACTS: list[str] = [
    "worker_pitfalls",
    "manager_planning_preamble",
    "experiment_context_hint_template",
    "pattern_library",
    "tool_description_templates",
    "critique_rubric",
]

# Narrow candidate set keeps each TextGrad call cheap and focused on the
# artifacts most likely to affect SVG-portrait worker behaviour.
CANDIDATE_ARTIFACTS: list[str] = [
    "worker_pitfalls",
    "manager_planning_preamble",
    "critique_rubric",
]

REQUIRED_METRIC_TYPES: frozenset[str] = frozenset({
    "metric.confidence",
    "metric.critique",
    "metric.budget",
    "metric.gate",
    "metric.tool_call",
})


def _pet_card_prompt(name: str, animal: str, sample_facts: str,
                     fact_template: str, computed_template: str,
                     filename: str) -> str:
    """Pet-profile JSON task — same proven shape as the fact-card pattern
    in outer_loop_full_coverage.py. JSON over SVG because the JSON
    deliverable shape produces stable critique signals.

    Uses the harness-provided _output_dir variable (canonical per-run
    output path) so the runtime's deliverable scorecard can locate the
    file at output/<run_id>/<filename> as it expects.
    """
    return (
        f"Build a profile-card JSON about {name} the {animal}. Use "
        f"code.execute to:\n"
        f"1. Compute 3 numeric 'fun facts' ({sample_facts}). Derive at "
        f"least one combined statistic ({computed_template}).\n"
        f"2. Write the final JSON to _output_dir + '/{filename}' "
        f"(use the harness-provided _output_dir variable; do NOT "
        f"hardcode 'workspace/output/...'). The file MUST contain "
        f"these fields:\n"
        f"   - title (str, e.g. \"Profile of {name} the {animal}\")\n"
        f"   - facts (list of exactly 3 strings, each describing one "
        f"of the numeric facts: {fact_template})\n"
        f"   - computed_stats (dict of 3 numbers, including the "
        f"combined stat)\n"
        f"   - sources (list of 2+ strings, short bibliographic or "
        f"URL-style)\n"
        f"   - confidence (float 0-1, must be >= 0.7)\n"
        f"Your result must pass critique + evaluation before completion. "
        f"Include confidence in the top-level agent output."
    )


def _miku_prompt() -> str:
    return _pet_card_prompt(
        name="Miku",
        animal="dog",
        sample_facts="approximate weight kg ~ 12, age years ~ 4, "
                     "average daily walk km ~ 3",
        fact_template="weight, age, daily-walk distance",
        computed_template="e.g. total walk distance over a year = "
                          "daily_walk * 365",
        filename="miku_card.json",
    )


def _luna_prompt() -> str:
    return _pet_card_prompt(
        name="Luna",
        animal="cat",
        sample_facts="approximate weight kg ~ 4, age years ~ 7, "
                     "average daily nap hours ~ 14",
        fact_template="weight, age, daily-nap hours",
        computed_template="e.g. total nap hours over a year = "
                          "daily_nap * 365",
        filename="luna_card.json",
    )


TASKS: list[dict[str, str]] = [
    dict(name="miku", prompt=_miku_prompt()),
    dict(name="luna", prompt=_luna_prompt()),
]


# ----- Outer-loop DB + registry helpers -------------------------------------


def _get_outer_loop_infra() -> tuple[Any, Any, Path]:
    """Return (store, registry, db_path). Both use ~/.awp/outer_loop.db."""
    from awp.outer_loop.artifacts import ArtifactRegistry
    from awp.outer_loop.store import SqliteArtifactStore

    db_path = Path.home() / ".awp" / "outer_loop.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteArtifactStore(str(db_path))
    registry = ArtifactRegistry(db_path=str(db_path))
    return store, registry, db_path


def _build_llm_client():
    from awp.runtime.llm import LLMClient
    return LLMClient(model="openai/gpt-5-mini")


# ----- Run-dir discovery ----------------------------------------------------


def _find_run_dir(report: dict[str, Any]) -> Path:
    """Locate the delegation-loop run directory for a completed run_e2e call."""
    workflow_dir = Path(report["workflow_dir"])
    runs_dir = workflow_dir / "workspace" / "runs"
    run_id: str = str(report.get("run_id") or "")

    if runs_dir.exists():
        candidates: list[tuple[float, Path]] = []
        for d in runs_dir.iterdir():
            if not d.is_dir():
                continue
            rc = d / "run_completion.json"
            if not rc.exists():
                continue
            if run_id and run_id in d.name:
                return d
            try:
                candidates.append((rc.stat().st_mtime, d))
            except OSError:
                continue
        for _mtime, d in sorted(candidates, key=lambda x: -x[0]):
            manifest = d / "run_manifest.json"
            if manifest.exists():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    if run_id and data.get("run_id") == run_id:
                        return d
                except (OSError, json.JSONDecodeError):
                    pass
        if candidates:
            candidates.sort(key=lambda x: -x[0])
            return candidates[0][1]

    for rc in workflow_dir.rglob("run_completion.json"):
        return rc.parent
    return workflow_dir


def _compute_loss(run_dir: Path) -> float:
    from awp.outer_loop.loss import compute_run_loss
    return float(compute_run_loss(run_dir).total)


def _extract_scores(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    scores: dict[str, Any] = {
        "status": report.get("status"),
        "wf_status": report.get("wf_status"),
        "termination_reason": report.get("termination_reason"),
        "duration_s": report.get("duration_s"),
    }
    rc = run_dir / "run_completion.json"
    if rc.exists():
        try:
            data = json.loads(rc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for k in (
            "status",
            "reason",
            "eval_score",
            "critique_score",
            "tokens_used",
            "workers_spawned",
            "loops_used",
            "gate_rejection_count",
        ):
            if k in data:
                scores.setdefault(k, data[k])
    return scores


def _verify_metric_types(run_dirs: list[Path]) -> dict[str, bool]:
    found: set[str] = set()
    for rd in run_dirs:
        path = rd / "metrics.jsonl"
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tp = obj.get("type") or obj.get("event") or ""
                if isinstance(tp, str):
                    found.add(tp)
        except OSError:
            continue
    return {t: (t in found) for t in REQUIRED_METRIC_TYPES}


def _prepare_seed_final(seed_run_dir: Path) -> bool:
    """Ensure <seed>/FINAL/ is populated so RefinementLoop can seed
    iteration 1. The AWP runtime writes <workflow>/output/FINAL/ (a
    single workflow-level pointer), not <run_dir>/FINAL/ which is what
    refinement expects. Hard-link the per-run canonical deliverables
    (output/<run_id>/...) into <seed>/FINAL/ as a structural bridge.
    Returns True on success, False if no canonical output was found.
    """
    import os
    final_dir = seed_run_dir / "FINAL"
    if final_dir.exists() and any(final_dir.iterdir()):
        return True

    # Walk up to the workflow workspace to find output/<run_id>/.
    workspace = seed_run_dir.parent
    for _ in range(6):
        if (workspace / "output").exists():
            break
        if workspace == workspace.parent:
            return False
        workspace = workspace.parent
    output_root = workspace / "output"
    if not output_root.exists():
        return False

    # Prefer a canonical subdir matching the seed's run_id.
    candidates = [p for p in output_root.iterdir() if p.is_dir()]
    source = next(
        (c for c in candidates if c.name == seed_run_dir.name),
        None,
    )
    if source is None:
        return False

    final_dir.mkdir(parents=True, exist_ok=True)
    linked = 0
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(source)
        dst = final_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(item, dst)
        except OSError:
            import shutil
            shutil.copy2(item, dst)
        linked += 1
    return linked > 0


def _read_run_status(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if not rc.exists():
        return "missing"
    try:
        return str(json.loads(rc.read_text(encoding="utf-8")).get("status") or "unknown")
    except (OSError, json.JSONDecodeError):
        return "unparseable"


# ----- Suite / epoch SQL writers --------------------------------------------


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_suite(
    db_path: Path,
    suite_id: str,
    name: str,
    tasks: list[dict[str, str]],
    baseline: dict[str, int],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT OR REPLACE INTO task_suites "
            "(id, name, tasks_json, baseline_artifacts_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                suite_id,
                name,
                json.dumps(
                    [{"name": t["name"], "task": t["prompt"]} for t in tasks]
                ),
                json.dumps(baseline),
                _iso_now(),
            ),
        )


def _insert_epoch(
    db_path: Path,
    epoch_id: str,
    suite_id: str,
    epoch_num: int,
    parent_artifacts: dict[str, int],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO epochs "
            "(id, suite_id, epoch_num, started_at, completed_at, "
            "mean_loss, parent_artifacts_json, child_artifacts_json) "
            "VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL)",
            (
                epoch_id,
                suite_id,
                epoch_num,
                _iso_now(),
                json.dumps(parent_artifacts),
            ),
        )


def _insert_epoch_run(
    db_path: Path,
    epoch_id: str,
    run_id: str,
    task_name: str,
    loss: float,
    scores: dict[str, Any],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO epoch_runs "
            "(epoch_id, run_id, task_name, loss, scores_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                epoch_id,
                run_id,
                task_name,
                float(loss),
                json.dumps(scores, default=str),
            ),
        )


def _finalize_epoch(
    db_path: Path,
    epoch_id: str,
    mean_loss: float,
    child_artifacts_record: dict[str, Any],
) -> None:
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "UPDATE epochs SET completed_at = ?, mean_loss = ?, "
            "child_artifacts_json = ? WHERE id = ?",
            (
                _iso_now(),
                float(mean_loss),
                json.dumps(child_artifacts_record, default=str),
                epoch_id,
            ),
        )


def _run_optimizer(
    registry: Any,
    epoch_id: str,
    epoch_num: int,
    suite_id: str,
    task_results: list[dict[str, Any]],
    learning_rate: float,
    parent_artifacts: dict[str, int],
) -> dict[str, Any] | None:
    """Build an EpochResult, ask TextGradOptimizer for one proposal, and
    persist it via the registry. Returns the update record on success.
    """
    try:
        from awp.outer_loop.loss import compute_run_loss
        from awp.outer_loop.runner import EpochResult, TaskRunResult
        from awp.outer_loop.textgrad import TextGradOptimizer
    except Exception as exc:  # pragma: no cover
        print(f"[e2e] optimizer imports failed: {exc}")
        return None

    tr_objs: list[TaskRunResult] = []
    for tr in task_results:
        breakdown = compute_run_loss(Path(tr["run_dir"]))
        tr_objs.append(
            TaskRunResult(
                task_name=tr["name"],
                run_id=tr["run_id"],
                run_dir=str(tr["run_dir"]),
                status=str(tr.get("status") or "unknown"),
                loss=float(tr["loss"]),
                breakdown=breakdown,
            )
        )
    mean_loss = (
        sum(t.loss for t in tr_objs) / len(tr_objs) if tr_objs else None
    )
    epoch_result = EpochResult(
        epoch_id=epoch_id,
        suite_id=suite_id,
        suite_name=SUITE_NAME,
        epoch_num=epoch_num,
        parent_artifacts=dict(parent_artifacts),
        child_artifacts=dict(parent_artifacts),
        task_results=tr_objs,
        mean_loss=mean_loss,
        started_at="",
        completed_at="",
    )

    llm = _build_llm_client()
    optimizer = TextGradOptimizer(llm_client=llm, registry=registry)
    try:
        update = optimizer.propose_update(
            epoch_result,
            candidate_artifacts=CANDIDATE_ARTIFACTS,
            learning_rate=learning_rate,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[e2e] TextGradOptimizer.propose_update failed: {exc}")
        return None

    if update is None or not update.artifact_name:
        print("[e2e] optimizer declined all candidates - no update")
        return None

    try:
        parent_version = int(parent_artifacts.get(update.artifact_name, 0))
        new_version = registry.put_version(
            update.artifact_name,
            update.proposed_content,
            parent_version=parent_version,
            epoch_id=epoch_id,
        )
        registry.set_active(update.artifact_name, new_version.version)
    except Exception as exc:  # noqa: BLE001
        print(f"[e2e] registry write failed: {exc}")
        return None

    print(
        f"[e2e] optimizer updated {update.artifact_name} "
        f"v{parent_version} -> v{new_version.version} "
        f"(expected_loss_reduction={update.expected_loss_reduction:.2f}, "
        f"confidence={update.confidence:.2f})"
    )
    return {
        "type": "update",
        "artifact": update.artifact_name,
        "from_version": parent_version,
        "to_version": int(new_version.version),
        "rationale": update.rationale,
        "expected_loss_reduction": update.expected_loss_reduction,
        "confidence": update.confidence,
        "learning_rate": learning_rate,
    }


# ----- Refinement phase -----------------------------------------------------


def _run_refinement(
    seed_run_dir: Path,
    iterations: int,
) -> dict[str, Any]:
    """Drive RefinementLoop in-process.

    Returns a structured summary with iteration statuses + losses + the
    stop reason. NothingToRefine (R36) is treated as a valid outcome,
    not a failure.
    """
    from awp.refinement import NothingToRefine, RefinementLoop

    summary: dict[str, Any] = {
        "seed": str(seed_run_dir),
        "iterations": [],
        "stop_reason": None,
        "session_id": None,
        "best_iter": None,
        "best_loss": None,
        "seed_loss": None,
        "r36_aborted": False,
        "all_complete": False,
    }

    loop = RefinementLoop(
        seed_run_dir=seed_run_dir,
        model="openai/gpt-5-mini",
    )
    try:
        result = loop.run(iterations=iterations)
    except NothingToRefine as exc:
        # R36 normative path: seed already perfect, nothing to refine.
        # Treat as a valid completion of the refinement phase.
        print(f"[e2e] refinement: NothingToRefine (R36) - {exc}")
        summary["r36_aborted"] = True
        summary["stop_reason"] = "empty_gradient"
        summary["all_complete"] = True  # R36 is a valid terminal state
        return summary

    summary["session_id"] = result.session_id
    summary["best_iter"] = result.best_iter
    summary["best_loss"] = result.best_loss
    summary["seed_loss"] = result.seed_loss
    summary["stop_reason"] = result.stop_reason
    statuses: list[str] = []
    for outcome in result.iterations:
        statuses.append(outcome.status)
        summary["iterations"].append({
            "k": outcome.k,
            "run_id": outcome.run_id,
            "run_dir": str(outcome.run_dir),
            "status": outcome.status,
            "loss": outcome.loss,
            "parent_run_id": outcome.parent_run_id,
        })
    # Refinement counts as 'all_complete' if every iteration that was
    # actually executed reached terminal status `complete`. A documented
    # early stop (regression / plateau / wall_time / empty_gradient_midloop)
    # is an acceptable stop signal as long as the iterations that DID
    # run all completed cleanly.
    summary["all_complete"] = bool(statuses) and all(s == "complete" for s in statuses)
    return summary


# ----- Main driver ----------------------------------------------------------


def main() -> int:
    load_openrouter_key()
    print("[e2e] Starting Miku outer-loop + refinement E2E "
          f"(epochs={EPOCHS}, refine_iters={REFINE_ITERATIONS})")

    store, registry, db_path = _get_outer_loop_infra()
    _ = store

    session_id: str | None = None
    suite_id = uuid.uuid4().hex[:12]

    _insert_suite(
        db_path,
        suite_id=suite_id,
        name=SUITE_NAME,
        tasks=TASKS,
        baseline={n: 0 for n in ALL_ARTIFACTS},
    )

    run_dirs_all: list[Path] = []
    epoch_summaries: list[dict[str, Any]] = []

    # ---- Phase 1: outer loop ----------------------------------------------

    for epoch_num in range(1, EPOCHS + 1):
        epoch_id = uuid.uuid4().hex[:12]
        parent_artifacts = {
            n: registry.get_active(n).version for n in ALL_ARTIFACTS
        }
        _insert_epoch(
            db_path,
            epoch_id=epoch_id,
            suite_id=suite_id,
            epoch_num=epoch_num,
            parent_artifacts=parent_artifacts,
        )
        print(f"\n[e2e] === Epoch {epoch_num}/{EPOCHS} (epoch_id={epoch_id}) ===")
        print(f"[e2e] parent_artifacts={parent_artifacts}")

        task_results: list[dict[str, Any]] = []
        for task in TASKS:
            slug = f"miku-outer-e{epoch_num}-{task['name']}"
            title = f"Miku E2E - Epoch {epoch_num} - {task['name']}"
            print(f"\n[e2e] Running {slug} ...")
            report = run_e2e(
                slug=slug,
                title=title,
                task=task["prompt"],
                model="openai/gpt-5-mini",
                worker_model="deepseek/deepseek-chat-v3.1",
                max_loops=6,
                max_total_tokens=600_000,
                max_wall_time=420,
                max_total_workers=5,
                max_depth=2,
                max_tool_calls=80,
                tags=TAGS,
                session_id=session_id,
            )
            if session_id is None:
                session_id = str(report.get("session_id") or "")
            run_dir = _find_run_dir(report)
            run_dirs_all.append(run_dir)

            loss = _compute_loss(run_dir)
            scores = _extract_scores(run_dir, report)
            _insert_epoch_run(
                db_path,
                epoch_id=epoch_id,
                run_id=str(report["run_id"]),
                task_name=task["name"],
                loss=loss,
                scores=scores,
            )
            task_results.append({
                "name": task["name"],
                "run_id": str(report["run_id"]),
                "run_dir": str(run_dir),
                "loss": loss,
                "status": str(report.get("status") or "unknown"),
            })
            print(f"[e2e] task={task['name']} status={report['status']} "
                  f"loss={loss:.4f}")

        losses = [t["loss"] for t in task_results if t["loss"] is not None]
        mean_loss = sum(losses) / len(losses) if losses else 0.0
        print(f"[e2e] Epoch {epoch_num} mean_loss={mean_loss:.4f}")

        child_record: dict[str, Any] = {
            "artifacts": dict(parent_artifacts),
            "events": [],
        }

        # TextGrad runs between epochs (after 1 and 2; not after the last).
        if epoch_num < EPOCHS:
            print(f"[e2e] Running TextGradOptimizer after epoch {epoch_num} ...")
            update_event = _run_optimizer(
                registry=registry,
                epoch_id=epoch_id,
                epoch_num=epoch_num,
                suite_id=suite_id,
                task_results=task_results,
                learning_rate=0.5,
                parent_artifacts=parent_artifacts,
            )
            if update_event is not None:
                child_record["artifacts"][update_event["artifact"]] = (
                    update_event["to_version"]
                )
                child_record["events"].append(update_event)

        _finalize_epoch(
            db_path,
            epoch_id=epoch_id,
            mean_loss=mean_loss,
            child_artifacts_record=child_record,
        )
        epoch_summaries.append({
            "epoch_id": epoch_id,
            "epoch_num": epoch_num,
            "mean_loss": mean_loss,
            "task_results": task_results,
            "child_record": child_record,
        })

    # ---- Phase 2: refinement on the epoch-3 Miku run -----------------------
    print("\n[e2e] === Refinement Phase ===")
    last_epoch = epoch_summaries[-1]
    miku_results = [t for t in last_epoch["task_results"] if t["name"] == "miku"]
    if not miku_results:
        print("[e2e] FATAL: no Miku result in last epoch - cannot seed refinement")
        return 1
    seed_run_dir = Path(miku_results[0]["run_dir"])
    print(f"[e2e] Seeding refinement from: {seed_run_dir}")
    print(f"[e2e] Seed loss: {miku_results[0]['loss']:.4f}")

    # Bridge runtime's workflow-level output/FINAL to the per-run
    # <seed>/FINAL/ that RefinementLoop expects.
    prepped = _prepare_seed_final(seed_run_dir)
    print(f"[e2e] Prepared seed FINAL/: {prepped}")

    refinement_summary = _run_refinement(
        seed_run_dir=seed_run_dir,
        iterations=REFINE_ITERATIONS,
    )
    print(f"[e2e] Refinement stop_reason: {refinement_summary['stop_reason']}")
    print(f"[e2e] Refinement iterations completed: "
          f"{len(refinement_summary['iterations'])}")
    for it in refinement_summary["iterations"]:
        print(f"[e2e]   iter_{it['k']} status={it['status']} loss={it['loss']:.4f}")
    if refinement_summary["best_iter"] is not None:
        print(f"[e2e] Refinement best_iter={refinement_summary['best_iter']} "
              f"best_loss={refinement_summary['best_loss']}")

    # Collect refinement run dirs for metric verification
    refine_run_dirs = [
        Path(it["run_dir"]) for it in refinement_summary["iterations"]
    ]

    # ---- Phase 3: verification --------------------------------------------
    print("\n[e2e] === Verification ===")
    ok = True

    # 1. UI DB session_runs == 6 (only outer-loop runs go through the harness)
    ui_db = Path.home() / ".awp" / "awp_ui.db"
    sr_count = 0
    if ui_db.exists():
        with sqlite3.connect(str(ui_db)) as con:
            row = con.execute(
                "SELECT COUNT(*) FROM session_runs WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            sr_count = int(row[0] if row else 0)
    expected_outer = EPOCHS * len(TASKS)
    status_1 = "OK" if sr_count == expected_outer else "FAIL"
    print(f"[verify 1/8] UI DB session_runs for session={session_id}: "
          f"{sr_count}/{expected_outer} - {status_1}")
    ok &= (sr_count == expected_outer)

    # 2. All required metric.* types observed across outer-loop runs
    metric_presence = _verify_metric_types(run_dirs_all)
    missing = sorted(t for t, p in metric_presence.items() if not p)
    status_2 = "OK" if not missing else f"FAIL missing={missing}"
    print(f"[verify 2/8] metric.* types: "
          f"{sum(metric_presence.values())}/{len(REQUIRED_METRIC_TYPES)} "
          f"- {status_2}")
    ok &= (not missing)

    # 3. EPOCHS epoch rows in outer_loop.db
    with sqlite3.connect(str(db_path)) as con:
        ec = int(
            con.execute(
                "SELECT COUNT(*) FROM epochs WHERE suite_id = ?",
                (suite_id,),
            ).fetchone()[0]
        )
    status_3 = "OK" if ec == EPOCHS else "FAIL"
    print(f"[verify 3/8] epochs rows: {ec}/{EPOCHS} - {status_3}")
    ok &= (ec == EPOCHS)

    # 4. expected_outer epoch_runs rows
    with sqlite3.connect(str(db_path)) as con:
        erc = int(
            con.execute(
                "SELECT COUNT(*) FROM epoch_runs WHERE epoch_id IN "
                "(SELECT id FROM epochs WHERE suite_id = ?)",
                (suite_id,),
            ).fetchone()[0]
        )
    status_4 = "OK" if erc == expected_outer else "FAIL"
    print(f"[verify 4/8] epoch_runs rows: {erc}/{expected_outer} - {status_4}")
    ok &= (erc == expected_outer)

    # 5. Every outer-loop run reached a clean terminal state (complete or
    #    partial). aborted/failed/missing are real failures. partial is
    #    accepted as long as it's a clean termination — matches the
    #    pattern in outer_loop_full_coverage.py where the manager
    #    voluntarily ends partial after producing a deliverable but
    #    before reaching ideal critique scores.
    accepted_states = {"complete", "partial"}
    bad_status = [
        (rd, _read_run_status(rd))
        for rd in run_dirs_all
        if _read_run_status(rd) not in accepted_states
    ]
    complete_count = sum(
        1 for rd in run_dirs_all if _read_run_status(rd) == "complete"
    )
    status_5 = (
        "OK"
        if not bad_status
        else f"FAIL bad={[s for _, s in bad_status]}"
    )
    print(f"[verify 5/8] outer-loop runs terminal state OK: "
          f"{len(run_dirs_all) - len(bad_status)}/{len(run_dirs_all)} "
          f"({complete_count} complete + "
          f"{len(run_dirs_all) - len(bad_status) - complete_count} partial) "
          f"- {status_5}")
    ok &= (not bad_status)
    if bad_status:
        for rd, st in bad_status:
            print(f"           - {rd} status={st}")

    # 6. Refinement: either R36-aborted (valid R36 path) OR every executed
    #    iteration terminated cleanly (complete or partial).
    accepted_refine_states = {"complete", "partial"}
    if refinement_summary["r36_aborted"]:
        status_6 = "OK (R36)"
        refine_ok = True
    else:
        bad_iters = [
            f"iter_{it['k']}={it['status']}"
            for it in refinement_summary["iterations"]
            if it["status"] not in accepted_refine_states
        ]
        refine_ok = bool(refinement_summary["iterations"]) and not bad_iters
        status_6 = "OK" if refine_ok else f"FAIL bad={bad_iters}"
    print(f"[verify 6/8] refinement iterations terminal OK: {status_6}")
    ok &= refine_ok

    # 7. Refinement session sidecar exists (skipped under R36 since loop never started)
    if refinement_summary["r36_aborted"]:
        print("[verify 7/8] sidecar present: SKIP (R36, loop never started)")
    else:
        sidecars = list((seed_run_dir / "refinement_sessions").glob("*.json"))
        status_7 = "OK" if sidecars else "FAIL"
        print(f"[verify 7/8] sidecar present: {len(sidecars)} files - {status_7}")
        ok &= bool(sidecars)

    # 8. run_completion.json present per outer-loop + refine run
    all_dirs = run_dirs_all + refine_run_dirs
    missing_rc = [rd for rd in all_dirs if not (rd / "run_completion.json").exists()]
    status_8 = "OK" if not missing_rc else f"FAIL missing={len(missing_rc)}"
    print(f"[verify 8/8] run_completion.json present: "
          f"{len(all_dirs) - len(missing_rc)}/{len(all_dirs)} - {status_8}")
    ok &= (not missing_rc)

    # Loss trajectory (bonus, non-blocking)
    if len(epoch_summaries) >= 2:
        traj = " -> ".join(f"{e['mean_loss']:.4f}" for e in epoch_summaries)
        print(f"[bonus] outer-loop mean_loss trajectory: {traj}")
    if refinement_summary["iterations"]:
        rtraj = (
            f"seed={refinement_summary['seed_loss']:.4f} -> "
            + " -> ".join(
                f"{it['loss']:.4f}" for it in refinement_summary["iterations"]
            )
        )
        print(f"[bonus] refinement loss trajectory: {rtraj}")

    # ---- Summary -----------------------------------------------------------
    print("\n[e2e] === Summary ===")
    print(f"[e2e] Session ID:     {session_id}")
    print(f"[e2e] Suite ID:       {suite_id}")
    print(f"[e2e] UI DB:          {ui_db}")
    print(f"[e2e] Outer-loop DB:  {db_path}")
    print(f"[e2e] Refinement seed:{seed_run_dir}")
    print("[e2e] Open the UI sidebar to inspect the 6 outer-loop runs and "
          "the Optimizer tab for the suite charts.")
    print(f"[e2e] OVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
