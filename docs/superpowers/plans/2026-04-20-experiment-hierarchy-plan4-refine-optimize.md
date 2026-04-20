# Plan 4 — Refine + Optimize Relocated Under Task

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** `awp refine --target <exp>:<task>` writes refinement sessions to `<task>/refinements/session_<ts>/` (no longer at `<seed>/refinement_sessions/`). `awp optimize --target <exp>:<task> SUITE.yaml` opens `<experiment>/outer_loop.db` (not global) and writes epoch-runs to `<task>/optimizations/suite_<ts>/epoch_<n>/runs/`. BEST-Finaliser recognises refine iterations and optimize-epoch-runs as candidates.

**Architecture:** Pure CLI-wrapper change on top of existing runtime. The `RefinementLoop` and `SuiteRunner` constructors already accept workspace paths (`iterations_root` / `output_dir`). Plan 4 only resolves the right paths from the `--target` key before instantiation. Post-run-hook is generalised: `_post_run_finalise(run_role=…)` stamps refine_iter / optimize_epoch_run instead of hardcoded `seed`.

**Spec refs:** `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` §4 decision 5, §5, §7.6, §7.7.

**Lessons baked in** (from Plans 1-3):
- `--target` flag name (no collision with existing `--task` free-text arg)
- `awp.continuation` registered in setuptools-find — Plan 4 adds no new sub-package
- Flat tests in `packages/awp-runtime/tests/test_*.py`
- Real `run_completion.json` schema (`eval.score`, not `evaluation.score`)
- Smoke test at Task 8, not just unit tests
- Pre-verify runtime API signatures before writing plan code

**Out of scope:**
- UI rendering of refinement sessions / optimize suites (Plan 5)
- Migration of legacy refinement state (Plan 6)
- Cross-experiment artifact sharing / outer-loop DB merging

---

## Known preconditions (verified)

- `RefinementLoop.__init__` accepts `iterations_root: Path | None`. Pass `<task>/refinements/session_<ts>/` and the loop writes `iter_k/` under it.
- `RefinementLoop.run()` writes the session sidecar via `write_session_sidecar(seed_run_dir, session)`. We MUST redirect that to write under `<task>/refinements/` instead of `<seed>/refinement_sessions/`. Minor API touch in `refinement/session.py`.
- `SuiteRunner.run_epoch(output_dir=Path)` honours `output_dir`. Pass `<task>/optimizations/suite_<ts>/epoch_<n>/` and it writes per-task runs under it.
- `SuiteRunner.__init__` takes `store: SqliteArtifactStore`. The store's path IS the `outer_loop.db` path. Open with `SqliteArtifactStore(<experiment>/outer_loop.db)`.
- BEST finaliser `compute_and_update_best(task_dir, new_run_dir, force_override)` doesn't care about `run_role` — it reads any `run_completion.json`. No changes needed there. The post-run hook is the one that stamps `run_role`.
- Post-run hook `_post_run_finalise` in `awp-core/src/awp/experiment/cli_handlers.py` hardcodes `run_role="seed"`. Needs a parameter.

---

## File structure

**Modified:**
- `packages/awp-core/src/awp/cli.py` — add `--target` to `awp refine` and `awp optimize` subparsers.
- `packages/awp-core/src/awp/experiment/cli_handlers.py` — generalise `_post_run_finalise(run_role=…)`; add `refine_task_aware` + `optimize_task_aware` dispatchers.
- `packages/awp-runtime/src/awp/refinement/loop.py` — accept optional `session_sidecar_dir` override to redirect sidecar persistence.
- `packages/awp-runtime/src/awp/refinement/session.py` — split `write_session_sidecar` into `write_session_sidecar_at(target_dir, session)` + keep the existing wrapper for back-compat.

**Created:**
- `packages/awp-core/tests/cli/test_refine_target_cli.py`
- `packages/awp-core/tests/cli/test_optimize_target_cli.py`
- `packages/awp-runtime/tests/test_refine_target_smoke.py` — end-to-end without LLM
- `packages/awp-runtime/tests/test_optimize_target_smoke.py`

---

## Task 1: Generalise `_post_run_finalise` with `run_role` parameter

**Files:**
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_run_task_cli.py` (extend existing test)

- [ ] **Step 1: Add a test for `run_role="refine_iter"`**

Append to `packages/awp-core/tests/cli/test_run_task_cli.py`:

```python
def test_post_run_finalise_accepts_run_role(env: dict, tmp_path: Path) -> None:
    """run_role parameter is plumbed into the DB row."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    task_id = json.loads(r.stdout)["task_id"]

    output_dir = tmp_path / exp_id / "tasks" / task_id / "refinements" / "session_x"
    run_id = "refine_iter_1"
    run_dir = output_dir / "output" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "paper.md").write_text("refined")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id, "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": 0.95}, "critique": {"defects": []}, "gate_rejections": 0,
    }))

    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=output_dir,
        run_id=run_id,
        exp_id=exp_id,
        task_key=f"{exp_id}:{task_id}",
        task_text="t",
        model="m",
        run_role="refine_iter",
    )
    assert rc == 0

    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT run_role FROM runs WHERE id = ?", (run_id,),
    ).fetchone()
    con.close()
    assert row["run_role"] == "refine_iter"
```

- [ ] **Step 2: Run — expect failure (unexpected-kwarg or still writing "seed")**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py::test_post_run_finalise_accepts_run_role -v
```

- [ ] **Step 3: Modify `_post_run_finalise` signature**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, change the signature of `_post_run_finalise`:

```python
def _post_run_finalise(
    output_dir: Path,
    run_id: str | None,
    exp_id: str,
    task_key: str,
    task_text: str,
    model: str,
    run_role: str = "seed",
) -> int:
```

Replace the hardcoded `run_role="seed"` on the `store.upsert_run_for_task(...)` call with the parameter:

```python
        await store.upsert_run_for_task(
            run_id=run_id,
            experiment_id=exp_id,
            task_id=task_key,
            run_role=run_role,
            ...
        )
```

- [ ] **Step 4: Verify + full CLI regression**

```
pytest packages/awp-core/tests/cli/ -v 2>&1 | tail -15
```

Expected: all green. Existing callers still work (default `run_role="seed"`).

- [ ] **Step 5: Commit**

```bash
git add packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_run_task_cli.py
git commit -m "feat(cli): _post_run_finalise accepts run_role parameter"
```

---

## Task 2: Extend `awp refine` CLI with `--target`

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Test:   `packages/awp-core/tests/cli/test_refine_target_cli.py`

**Background.** Keep the existing `awp refine <seed_run_dir>` invocation. Add `--target <exp>:<task>` as an alternative; when present, `seed` becomes optional and the runner auto-resolves the task's BEST run (or seed-run's output dir) as the seed.

- [ ] **Step 1: Write failing tests**

Create `packages/awp-core/tests/cli/test_refine_target_cli.py`:

```python
"""CLI-level tests for `awp refine --target`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_refine_target_rejects_missing_task(env: dict) -> None:
    r = _run_cli(["refine", "--target", "exp_nosuch1:001-x"], env=env)
    assert r.returncode != 0
    lower = (r.stderr + r.stdout).lower()
    assert "not found" in lower or "experiment" in lower


def test_refine_target_rejects_task_without_best(env: dict, tmp_path: Path) -> None:
    """Refinement needs a completed run under the task; without BEST/, reject."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]
    # No BEST/ under the task
    r = _run_cli(["refine", "--target", f"{exp_id}:{tid}"], env=env)
    assert r.returncode != 0
    lower = (r.stderr + r.stdout).lower()
    assert "best" in lower


def test_refine_target_dry_run_computes_session_dir(env: dict, tmp_path: Path) -> None:
    """DRY_RUN prints the computed session dir + seed resolution."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    # Build fake BEST pointing at a fake run
    task_dir = tmp_path / exp_id / "tasks" / tid
    best = task_dir / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text(json.dumps({
        "winner_run_id": "seed_run_1",
        "winner_source": str(task_dir / "seed" / "output" / "seed_run_1"),
        "reason": "auto_loss", "loss": 0.4,
    }))

    env2 = env.copy()
    env2["AWP_REFINE_TARGET_DRY_RUN"] = "1"
    r = _run_cli(["refine", "--target", f"{exp_id}:{tid}"], env=env2)
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    assert str(task_dir / "refinements") in payload["iterations_root"]
    assert payload["seed_run_dir"].endswith("seed_run_1")
    assert payload["target"] == f"{exp_id}:{tid}"
```

- [ ] **Step 2: Run — expect failure**

```
pytest packages/awp-core/tests/cli/test_refine_target_cli.py -v
```

- [ ] **Step 3: Make `seed` positional optional on the `refine` subparser**

In `packages/awp-core/src/awp/cli.py`, find the `awp refine` subparser registration (around line 218). Change:

```python
    p_refine.add_argument("seed", ...)  # current: required positional
```

to:

```python
    p_refine.add_argument("seed", nargs="?", default=None, help="Seed run directory (or use --target)")
    p_refine.add_argument(
        "--target",
        default=None,
        help="Attach refinement to a task: <experiment_id>:<task_id>",
    )
```

- [ ] **Step 4: Add target dispatch at the top of `cmd_refine`**

In `cmd_refine` (cli.py around line 3245), insert at the top:

```python
    if getattr(args, "target", None) is not None:
        from .experiment.cli_handlers import refine_task_aware
        return refine_task_aware(args)
    if args.seed is None:
        print("awp refine: either a seed path or --target is required", file=sys.stderr)
        return 2
```

- [ ] **Step 5: Implement `refine_task_aware` in cli_handlers.py**

Add to `packages/awp-core/src/awp/experiment/cli_handlers.py`:

```python
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
```

- [ ] **Step 6: Verify**

```
pytest packages/awp-core/tests/cli/test_refine_target_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_refine_target_cli.py
git commit -m "feat(cli): awp refine --target (session under <task>/refinements/)"
```

---

## Task 3: Redirect session sidecar to `<task>/refinements/`

**Files:**
- Modify: `packages/awp-runtime/src/awp/refinement/session.py`
- Modify: `packages/awp-runtime/src/awp/refinement/loop.py`
- Test:   `packages/awp-runtime/tests/test_refinement_session_placement.py` (new)

**Background.** Today `RefinementLoop.run()` calls `write_session_sidecar(seed_run_dir, session)` which persists to `<seed_run_dir>/refinement_sessions/<session_id>.json`. For target-attached refinements, the sidecar must live under the task's session dir instead.

- [ ] **Step 1: Write the test**

Create `packages/awp-runtime/tests/test_refinement_session_placement.py`:

```python
"""Sidecar + BEST pointer placement for target-attached refinement."""

from __future__ import annotations

from pathlib import Path

from awp.refinement.session import RefinementSession, write_session_sidecar_at


def test_write_session_sidecar_at_custom_dir(tmp_path: Path) -> None:
    target = tmp_path / "task" / "refinements" / "session_x"
    session = RefinementSession(
        session_id="session_x",
        seed_run_id="seed_run_1",
        started_at="2026-04-20T00:00:00Z",
        completed_at="2026-04-20T00:05:00Z",
        stop_reason="max_iterations",
        best_iter=2,
        iterations=[],
    )
    path = write_session_sidecar_at(target_dir=target, session=session)
    assert path.exists()
    assert path == target / "session.json"
```

- [ ] **Step 2: Run — expect failure (function missing)**

```
pytest packages/awp-runtime/tests/test_refinement_session_placement.py -v
```

- [ ] **Step 3: Add `write_session_sidecar_at`**

In `packages/awp-runtime/src/awp/refinement/session.py`, add a new function beside the existing `write_session_sidecar`:

```python
def write_session_sidecar_at(target_dir: Path, session: RefinementSession) -> Path:
    """Persist the session JSON to a caller-supplied directory as `session.json`."""
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "session.json"
    path.write_text(session.to_json(), encoding="utf-8")
    return path
```

Do NOT remove or alter `write_session_sidecar` — the legacy refine flow still uses it for `<seed>/refinement_sessions/<id>.json`.

- [ ] **Step 4: Add `session_sidecar_dir` param to `RefinementLoop.__init__`**

In `packages/awp-runtime/src/awp/refinement/loop.py`, extend `RefinementLoop.__init__`:

```python
    def __init__(
        self,
        seed_run_dir: Path,
        workflow_factory=None,
        iterations_root: Path | None = None,
        model: str | None = None,
        worker_model: str | None = None,
        tier_plan=None,
        session_sidecar_dir: Path | None = None,  # NEW
    ) -> None:
        ...
        self._session_sidecar_dir = session_sidecar_dir
```

Where `RefinementLoop.run()` calls `write_session_sidecar(self._seed, session)` — add a conditional:

```python
        if self._session_sidecar_dir is not None:
            from .session import write_session_sidecar_at
            write_session_sidecar_at(self._session_sidecar_dir, session)
        else:
            write_session_sidecar(self._seed, session)
```

- [ ] **Step 5: Wire it from the CLI handler**

In `cli_handlers.py::refine_task_aware` (added in Task 2), update the `RefinementLoop(...)` construction to pass `session_sidecar_dir=iterations_root`:

```python
    loop = RefinementLoop(
        seed_run_dir=seed_run_dir,
        iterations_root=iterations_root,
        model=getattr(args, "model", None),
        worker_model=getattr(args, "worker_model", None),
        session_sidecar_dir=iterations_root,
    )
```

- [ ] **Step 6: Verify tests**

```
pytest packages/awp-runtime/tests/test_refinement_session_placement.py packages/awp-runtime/tests/refinement/ -v 2>&1 | tail -15
```

Expected: new test passes + no regression in existing refinement tests.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-runtime/src/awp/refinement/session.py packages/awp-runtime/src/awp/refinement/loop.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-runtime/tests/test_refinement_session_placement.py
git commit -m "feat(refine): session_sidecar_dir override for target-attached runs"
```

---

## Task 4: Extend `awp optimize` CLI with `--target`

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_optimize_target_cli.py`

**Background.** `awp optimize SUITE.yaml` already takes `--db`, `--output-dir`, `--epochs`, `--with-textgrad`, `--learning-rate`. Add `--target <exp>:<task>` that sets `--db` to `<experiment>/outer_loop.db` and `--output-dir` to `<task>/optimizations/suite_<ts>/`. Both flags remain available; `--target` just supplies defaults.

- [ ] **Step 1: Write failing tests**

Create `packages/awp-core/tests/cli/test_optimize_target_cli.py`:

```python
"""CLI-level tests for `awp optimize --target`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_optimize_target_rejects_missing_task(env: dict, tmp_path: Path) -> None:
    suite = tmp_path / "s.yaml"
    suite.write_text("name: s\ndescription: s\nbaseline_artifacts: {}\ntasks: []\n")
    r = _run_cli(
        ["optimize", str(suite), "--target", "exp_nosuch1:001-x"], env=env,
    )
    assert r.returncode != 0
    assert "not found" in (r.stderr + r.stdout).lower()


def test_optimize_target_dry_run_resolves_paths(env: dict, tmp_path: Path) -> None:
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]
    suite = tmp_path / "s.yaml"
    suite.write_text("name: s\ndescription: s\nbaseline_artifacts: {}\ntasks: []\n")

    env2 = env.copy()
    env2["AWP_OPTIMIZE_TARGET_DRY_RUN"] = "1"
    r = _run_cli(
        ["optimize", str(suite), "--target", f"{exp_id}:{tid}"], env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    payload = json.loads(r.stdout)
    assert payload["db_path"].endswith(f"{exp_id}/outer_loop.db")
    assert str(tmp_path / exp_id / "tasks" / tid / "optimizations") in payload["output_dir"]
    assert payload["target"] == f"{exp_id}:{tid}"
```

- [ ] **Step 2: Run — expect failure**

```
pytest packages/awp-core/tests/cli/test_optimize_target_cli.py -v
```

- [ ] **Step 3: Add `--target` to the `optimize` subparser**

In `packages/awp-core/src/awp/cli.py`, find `p_optimize = subparsers.add_parser("optimize", ...)` (around line 145). Append:

```python
    p_optimize.add_argument(
        "--target",
        default=None,
        help="Attach optimization to a task: <experiment_id>:<task_id>. "
             "Sets --db and --output-dir from the task's hierarchy.",
    )
```

- [ ] **Step 4: Add target dispatch at top of `cmd_optimize`**

In `cmd_optimize` (cli.py around line 2991), at the top of the function:

```python
    if getattr(args, "target", None) is not None:
        from .experiment.cli_handlers import optimize_task_aware
        return optimize_task_aware(args)
```

- [ ] **Step 5: Implement `optimize_task_aware`**

Add to `cli_handlers.py`:

```python
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
```

- [ ] **Step 6: Verify + regression**

```
pytest packages/awp-core/tests/cli/test_optimize_target_cli.py -v
pytest packages/awp-core/tests/cli/ 2>&1 | tail -5
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_optimize_target_cli.py
git commit -m "feat(cli): awp optimize --target (per-experiment DB + per-task suite dir)"
```

---

## Task 5: Refine smoke test (end-to-end, no LLM)

**Files:**
- Create: `packages/awp-runtime/tests/test_refine_target_smoke.py`

**Background.** Reuse the "build fake completed run + call finaliser" pattern from Plan 3. Simulate a refinement by building fake `iter_1/` + `iter_2/` dirs and calling the finaliser per iteration to verify BEST updates.

- [ ] **Step 1: Write the smoke test**

Create `packages/awp-runtime/tests/test_refine_target_smoke.py`:

```python
"""End-to-end smoke test for refine --target (no LLM)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def _mk_fake_run(dir_: Path, run_id: str, score: float) -> None:
    rd = dir_ / "output" / run_id
    rd.mkdir(parents=True)
    (rd / "FINAL").mkdir()
    (rd / "FINAL" / "paper.md").write_text(f"draft-{run_id}")
    (rd / "events.jsonl").write_text("")
    (rd / "metrics.jsonl").write_text("")
    (rd / "run_completion.json").write_text(json.dumps({
        "run_id": run_id, "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": score}, "critique": {"defects": []}, "gate_rejections": 0,
    }))


def test_refine_iterations_update_task_best(env: dict, tmp_path: Path) -> None:
    """Refinement iterations compete for BEST on a shared task."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    # Seed run
    seed_dir = tmp_path / exp_id / "tasks" / tid / "seed"
    _mk_fake_run(seed_dir, "seed_run_1", score=0.5)
    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    cli_handlers._post_run_finalise(
        output_dir=seed_dir, run_id="seed_run_1", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="t", model="m", run_role="seed",
    )

    # Refine iterations: iter_1 worse, iter_2 better
    refine_root = tmp_path / exp_id / "tasks" / tid / "refinements" / "session_abc"
    iter_1 = refine_root / "iter_1"
    iter_2 = refine_root / "iter_2"
    _mk_fake_run(iter_1, "iter_1_run", score=0.3)
    _mk_fake_run(iter_2, "iter_2_run", score=0.95)

    # Finalise each iter — should only win when score improves
    cli_handlers._post_run_finalise(
        output_dir=iter_1, run_id="iter_1_run", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="refine", model="m",
        run_role="refine_iter",
    )
    cli_handlers._post_run_finalise(
        output_dir=iter_2, run_id="iter_2_run", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="refine", model="m",
        run_role="refine_iter",
    )

    # Task BEST should now point at iter_2 (lowest loss)
    best = tmp_path / exp_id / "tasks" / tid / "BEST"
    m = json.loads((best / "manifest.json").read_text())
    assert m["winner_run_id"] == "iter_2_run"

    # DB should record all three runs with correct roles
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, run_role FROM runs WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    ).fetchall()
    con.close()
    roles = {r["id"]: r["run_role"] for r in rows}
    assert roles["seed_run_1"] == "seed"
    assert roles["iter_1_run"] == "refine_iter"
    assert roles["iter_2_run"] == "refine_iter"
```

- [ ] **Step 2: Run**

```
pytest packages/awp-runtime/tests/test_refine_target_smoke.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add packages/awp-runtime/tests/test_refine_target_smoke.py
git commit -m "test(refine): smoke-test for refine iterations competing for task BEST"
```

---

## Task 6: Optimize smoke test (end-to-end, no LLM)

**Files:**
- Create: `packages/awp-runtime/tests/test_optimize_target_smoke.py`

- [ ] **Step 1: Write the smoke test**

Create `packages/awp-runtime/tests/test_optimize_target_smoke.py`:

```python
"""End-to-end smoke test for optimize --target (no LLM, dry-run path only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "awp", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_optimize_target_creates_per_exp_db_path(env: dict, tmp_path: Path) -> None:
    """DRY_RUN shows that the resolved db_path lives under the experiment dir."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    suite = tmp_path / "s.yaml"
    suite.write_text("name: s\ndescription: s\nbaseline_artifacts: {}\ntasks: []\n")

    env2 = env.copy()
    env2["AWP_OPTIMIZE_TARGET_DRY_RUN"] = "1"
    r = _run_cli(
        ["optimize", str(suite), "--target", f"{exp_id}:{tid}"], env=env2,
    )
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    expected_db = tmp_path / exp_id / "outer_loop.db"
    expected_output_prefix = tmp_path / exp_id / "tasks" / tid / "optimizations"
    assert payload["db_path"] == str(expected_db)
    assert payload["output_dir"].startswith(str(expected_output_prefix))


def test_optimize_task_aware_finalise_records_epoch_run_role(
    env: dict, tmp_path: Path,
) -> None:
    """_post_run_finalise accepts run_role='optimize_epoch_run'."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    tid = json.loads(r.stdout)["task_id"]

    opt_dir = tmp_path / exp_id / "tasks" / tid / "optimizations" / "suite_x" / "epoch_1"
    opt_dir.mkdir(parents=True)
    run_dir = opt_dir / "output" / "epoch_run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "x.md").write_text("x")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": "epoch_run_1", "status": "complete", "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": 0.8}, "critique": {"defects": []}, "gate_rejections": 0,
    }))

    import importlib
    ch = importlib.import_module("awp.experiment.cli_handlers")
    rc = ch._post_run_finalise(
        output_dir=opt_dir, run_id="epoch_run_1", exp_id=exp_id,
        task_key=f"{exp_id}:{tid}", task_text="opt", model="m",
        run_role="optimize_epoch_run",
    )
    assert rc == 0

    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT run_role FROM runs WHERE id = ?", ("epoch_run_1",),
    ).fetchone()
    con.close()
    assert row["run_role"] == "optimize_epoch_run"
```

- [ ] **Step 2: Run + Commit**

```
pytest packages/awp-runtime/tests/test_optimize_target_smoke.py -v
git add packages/awp-runtime/tests/test_optimize_target_smoke.py
git commit -m "test(optimize): smoke-test for target resolution + epoch_run_role"
```

---

## Task 7: Docs — CLAUDE.md + continuation.md reference + refinement.md note

- [ ] **Step 1: Update CLAUDE.md Development Commands**

Append to the existing Development Commands block:

```
# Target-aware refinement + optimization (Plan 4)
awp refine --target <experiment_id>:<task_id>     # refine task's BEST run;
                                                   # session under <task>/refinements/
awp optimize <suite>.yaml --target <experiment_id>:<task_id>
                                                   # per-experiment outer_loop.db;
                                                   # epoch-runs under <task>/optimizations/
```

- [ ] **Step 2: Update `docs/refinement.md` with a section "Task-attached refinement"**

Add a short section at the end of `docs/refinement.md` (if file exists; else create) explaining the new `--target` mode and the session-dir relocation. Reference `packages/awp-core/src/awp/experiment/cli_handlers.py::refine_task_aware`.

- [ ] **Step 3: Update `docs/outer-loop.md`**

Add a section "Per-experiment DB" explaining that `--target` overrides `--db` to `<experiment>/outer_loop.db`, implementing spec decision β (isolation).

- [ ] **Step 4: Drift gates**

```
python scripts/check_docs_drift.py && echo DRIFT_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/refinement.md docs/outer-loop.md
git commit -m "docs: document awp refine/optimize --target (Plan 4)"
```

---

## Task 8: Mirror sync + full regression

- [ ] **Step 1: Full regression**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" 2>&1 | tail -5
```

Expected: all green (Plan 3 fixed the pre-existing outer-loop test in commit `b00943c`).

- [ ] **Step 2: Sync mirror**

```
rsync -a packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a packages/awp-ui/server/ reference/python/src/server/
```

- [ ] **Step 3: Drift gates**

```
python scripts/check_mirror_drift.py && echo MIRROR_OK
python scripts/check_docs_drift.py && echo DOCS_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 4: Commit**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with Plan 4 (refine/optimize --target)"
```

---

## Self-review

- `awp refine --target <exp>:<task>` resolves BEST, writes session under `<task>/refinements/session_<ts>/`, finalises each iter_k with `run_role="refine_iter"`.
- `awp optimize --target <exp>:<task> SUITE.yaml` opens `<experiment>/outer_loop.db`, writes epoch-runs under `<task>/optimizations/suite_<ts>/`.
- Task's BEST manifest correctly ranks across seed, refine, optimize runs.
- `_post_run_finalise` accepts `run_role` without breaking existing seed callers.
- All drift gates green.

## Handoff to Plan 5

Plan 5 picks up the UI: sidebar tree (Experiment → Task → {seed, refinements, optimizations}), Experiment/Task detail views with loss curves, BEST-override action. Plan 4's artefacts (`<task>/refinements/session_<ts>/session.json`, `<task>/optimizations/suite_<ts>/suite.json`) are the UI's data sources.
