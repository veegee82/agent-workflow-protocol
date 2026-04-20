# Plan 6 — Cleanup: Purge-Legacy + Final Doc Sweep + Regression

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Close out the experiment-hierarchy arc. (1) Ship `awp experiment purge-legacy` to clean flat-layout junk. (2) Make sure every architecture doc (`CLAUDE.md`, `docs/continuation.md`, `docs/refinement.md`, `docs/outer-loop.md`, spec) cross-links the hierarchy concepts. (3) Final end-to-end regression pass.

**Architecture:** Pure cleanup. No runtime changes, no new features. Every task is either a delete-with-confirmation command, a doc cross-link fix, or a test sweep.

**Spec refs:** spec §13 Migration.

**Lessons baked in (Plans 1-5):**
- **No rewrites of `CLAUDE.md`.** After Plan 4 Task 7's gutting, Plan 6 appends only. If a task wants to restructure, it MUST STOP and escalate.
- Flat tests, real run_completion schema (`eval.score`), smoke-test at end.
- `awp.experiment` in awp-core exists; no new sub-package needed on the Python side.
- Frontend coexistence — `SessionSidebar` + `ExperimentSidebar` both stay.

**Out of scope:**
- UI WebSocket push for new experiments (Plan 5 uses poll-on-navigation; a future polish item).
- Outer-loop-history tab rendering artifact-version diffs (spec §9.2 mentions — data loader not wired; defer).
- Retiring `sessions` / `session_runs` tables (spec §6.3 open question; dead code tolerable; defer).
- Real-LLM end-to-end (covered by existing `e2e` tagged tests; Plan 6 does not add new ones).

---

## File structure

**Created:**
- `packages/awp-core/tests/cli/test_purge_legacy_cli.py` — purge-legacy CLI tests.
- `packages/awp-runtime/tests/test_full_hierarchy_pipeline_smoke.py` — single consolidated smoke test that exercises the entire Plans-1-through-5 happy path end-to-end without an LLM.

**Modified:**
- `packages/awp-core/src/awp/cli.py` — add `awp experiment purge-legacy` subparser.
- `packages/awp-core/src/awp/experiment/cli_handlers.py` — implement `_purge_legacy_experiments`.
- `CLAUDE.md` — append a "Hierarchy — cross-reference" note under the existing UI section (APPEND only).
- `docs/continuation.md` — add a short "See also" block linking refinement + outer-loop.
- `docs/refinement.md` — add a "See also" block linking continuation + outer-loop.
- `docs/outer-loop.md` — add a "See also" block linking continuation + refinement.

---

## Task 1: `awp experiment purge-legacy` CLI

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test: `packages/awp-core/tests/cli/test_purge_legacy_cli.py`

**Background.** Spec §13.1 defines this command. It: (1) enumerates directories under `/tmp/awp-experiments/` (or `$AWP_EXPERIMENTS_ROOT`), (2) identifies those **without** an `experiment.json` at their root (= legacy flat-layout runs), (3) prompts confirmation unless `--yes`, (4) deletes them, (5) deletes `runs` rows in `awp_ui.db` where `experiment_id IS NULL`.

### Steps

- [ ] **Step 1: Write failing tests**

Create `packages/awp-core/tests/cli/test_purge_legacy_cli.py`:

```python
"""CLI tests for `awp experiment purge-legacy`."""

from __future__ import annotations

import json
import os
import sqlite3
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


def test_purge_legacy_deletes_flat_dirs(env: dict, tmp_path: Path) -> None:
    # Build a legacy flat dir (no experiment.json at root)
    legacy = tmp_path / "legacy-run-abc123"
    legacy.mkdir()
    (legacy / "run_completion.json").write_text('{"run_id":"abc123"}')

    # Build a hierarchy dir (has experiment.json)
    r = _run_cli(["experiment", "create", "H"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    hierarchy = tmp_path / exp_id
    assert hierarchy.exists()
    assert (hierarchy / "experiment.json").exists()

    # Run purge with --yes
    r = _run_cli(["experiment", "purge-legacy", "--yes"], env=env)
    assert r.returncode == 0, r.stderr

    # Legacy gone, hierarchy preserved
    assert not legacy.exists()
    assert hierarchy.exists()


def test_purge_legacy_lists_before_delete(env: dict, tmp_path: Path) -> None:
    """Without --yes, purge prints the list and prompts (we skip input + abort)."""
    legacy = tmp_path / "legacy-xyz"
    legacy.mkdir()

    # Send "n\n" to stdin to decline confirmation
    r = subprocess.run(
        [sys.executable, "-m", "awp", "experiment", "purge-legacy"],
        capture_output=True, text=True, env=env, input="n\n",
    )
    assert r.returncode != 0 or "aborted" in (r.stderr + r.stdout).lower()
    # Directory still present after decline
    assert legacy.exists()


def test_purge_legacy_deletes_orphan_runs_rows(env: dict, tmp_path: Path) -> None:
    """`runs` rows with experiment_id IS NULL are deleted."""
    db = tmp_path / "awp_ui.db"

    # Seed the DB with: one orphan run + one hierarchy-attached run
    from server.services.store import StoreService
    import asyncio

    async def _seed():
        s = StoreService(db_path=db)
        await s.init_db()
        # Hierarchy experiment + task + run
        await s.create_experiment("exp_x", "E", "", str(tmp_path / "exp_x"), 1.0)
        await s.create_task("exp_x:001-s", "exp_x", 1, "s", "seed", "p", None, "[]", 1.0)
        await s.upsert_run_for_task(
            "kept_run", "exp_x", "exp_x:001-s", "seed", 0.3, "complete", "t", "m",
        )
        # Orphan: insert raw (no experiment_id)
        import time
        await s.db.execute(
            "INSERT INTO runs (id, task, model, status, config_json, created_at) "
            "VALUES (?, ?, ?, ?, '{}', ?)",
            ("orphan_run", "legacy", "m", "complete", str(time.time())),
        )
        await s.db.commit()
        await s.close()

    asyncio.run(_seed())

    r = _run_cli(["experiment", "purge-legacy", "--yes"], env=env)
    assert r.returncode == 0, r.stderr

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, experiment_id FROM runs").fetchall()
    con.close()
    ids = {row["id"]: row["experiment_id"] for row in rows}
    assert "kept_run" in ids
    assert ids["kept_run"] == "exp_x"
    assert "orphan_run" not in ids
```

- [ ] **Step 2: Run — expect `unrecognized arguments: purge-legacy`**

```
pytest packages/awp-core/tests/cli/test_purge_legacy_cli.py -v
```

- [ ] **Step 3: Register the subparser**

In `packages/awp-core/src/awp/cli.py`, find the `experiment` subparser block (added in Plan 1). Add a new sub-subcommand after the existing `create/list/show/delete`:

```python
    p_exp_purge = exp_sub.add_parser(
        "purge-legacy",
        help="Delete flat-layout (pre-hierarchy) experiment directories and orphan runs rows",
    )
    p_exp_purge.add_argument("--yes", action="store_true", help="skip confirmation")
```

- [ ] **Step 4: Extend `handle_experiment_command`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, add a branch in `handle_experiment_command`:

```python
    if cmd == "purge-legacy":
        return _purge_legacy_experiments(args.yes)
```

And implement:

```python
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
```

- [ ] **Step 5: Verify**

```
pytest packages/awp-core/tests/cli/test_purge_legacy_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_purge_legacy_cli.py
git commit -m "feat(cli): awp experiment purge-legacy (flat dirs + orphan runs rows)"
```

---

## Task 2: Full-hierarchy end-to-end smoke test

**Files:**
- Create: `packages/awp-runtime/tests/test_full_hierarchy_pipeline_smoke.py`

**Background.** Plans 1-5 each shipped their own smoke test; Plan 6 adds one **consolidated** test that exercises the whole arc — experiment + seed task + seed run + continuation task + refine session + optimize suite (all as fake runs, no LLM) — and asserts the final state is coherent. This protects against regressions across the plans touching each other.

- [ ] **Step 1: Implement**

Create `packages/awp-runtime/tests/test_full_hierarchy_pipeline_smoke.py`:

```python
"""Consolidated smoke test — Plans 1-5 combined pipeline (no LLM)."""

from __future__ import annotations

import json
import os
import sqlite3
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


def test_full_arc_seed_continuation_refine_optimize(env: dict, tmp_path: Path) -> None:
    """End-to-end: experiment → seed task → continuation task → refine → optimize.

    Every step uses the real CLI. Runs are faked (no LLM).
    """
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    # ---- Plan 1: create experiment + seed task
    r = _run_cli(["experiment", "create", "Full-Arc"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "Write paper"], env=env)
    seed_task_id = json.loads(r.stdout)["task_id"]

    # ---- Plan 2: fake seed run + post-finalise
    seed_dir = tmp_path / exp_id / "tasks" / seed_task_id / "seed"
    _mk_fake_run(seed_dir, "seed_r1", score=0.5)
    import importlib
    ch = importlib.import_module("awp.experiment.cli_handlers")
    ch._post_run_finalise(
        output_dir=seed_dir, run_id="seed_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{seed_task_id}", task_text="Write paper",
        model="m", run_role="seed",
    )

    # Assert: seed task has BEST
    seed_best = tmp_path / exp_id / "tasks" / seed_task_id / "BEST"
    assert (seed_best / "manifest.json").exists()
    assert (seed_best / "paper.md").read_text() == "draft-seed_r1"

    # ---- Plan 3: create continuation task + fake its seed run
    r = _run_cli(
        [
            "task", "create", exp_id, "deepen sec 3",
            "--continuation", "--from-task", seed_task_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_task_id = json.loads(r.stdout)["task_id"]

    # Dry-run the continuation dispatch to verify the prefix builds
    capture = tmp_path / "captured.json"
    env2 = env.copy()
    env2["AWP_CONTINUATION_CAPTURE_ONLY"] = str(capture)
    r = _run_cli(
        [
            "run", "nonexistent.yaml", "--task", "ignored",
            "--target", f"{exp_id}:{cont_task_id}",
        ],
        env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    cap = json.loads(capture.read_text())
    assert "## Continuation Context" in cap["manager_prompt_prefix"]
    assert "draft-seed_r1" in cap["manager_prompt_prefix"]

    cont_dir = tmp_path / exp_id / "tasks" / cont_task_id / "seed"
    _mk_fake_run(cont_dir, "cont_r1", score=0.8)
    ch._post_run_finalise(
        output_dir=cont_dir, run_id="cont_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{cont_task_id}", task_text="deepen sec 3",
        model="m", run_role="seed",
    )
    cont_best = tmp_path / exp_id / "tasks" / cont_task_id / "BEST"
    assert (cont_best / "manifest.json").exists()

    # ---- Plan 4: fake refine iteration for seed_task (better loss)
    refine_root = (
        tmp_path / exp_id / "tasks" / seed_task_id / "refinements" / "session_x"
    )
    iter_1 = refine_root / "iter_1"
    _mk_fake_run(iter_1, "refine_r1", score=0.95)
    ch._post_run_finalise(
        output_dir=iter_1, run_id="refine_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{seed_task_id}", task_text="refine", model="m",
        run_role="refine_iter",
    )
    seed_best_m = json.loads((seed_best / "manifest.json").read_text())
    # refine_r1 beats seed_r1 since score 0.95 > 0.5 → lower loss
    assert seed_best_m["winner_run_id"] == "refine_r1"

    # ---- Plan 4: fake optimize epoch run (even better loss)
    opt_root = (
        tmp_path / exp_id / "tasks" / seed_task_id / "optimizations"
        / "suite_x" / "epoch_1"
    )
    _mk_fake_run(opt_root, "opt_r1", score=0.99)
    ch._post_run_finalise(
        output_dir=opt_root, run_id="opt_r1", exp_id=exp_id,
        task_key=f"{exp_id}:{seed_task_id}", task_text="opt",
        model="m", run_role="optimize_epoch_run",
    )
    seed_best_m = json.loads((seed_best / "manifest.json").read_text())
    assert seed_best_m["winner_run_id"] == "opt_r1"

    # ---- Plan 5-ish: DB state is coherent
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, run_role FROM runs WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    ).fetchall()
    con.close()
    roles = {r["id"]: r["run_role"] for r in rows}
    assert roles["seed_r1"] == "seed"
    assert roles["cont_r1"] == "seed"
    assert roles["refine_r1"] == "refine_iter"
    assert roles["opt_r1"] == "optimize_epoch_run"
```

- [ ] **Step 2: Run**

```
pytest packages/awp-runtime/tests/test_full_hierarchy_pipeline_smoke.py -v
```

Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add packages/awp-runtime/tests/test_full_hierarchy_pipeline_smoke.py
git commit -m "test(runtime): consolidated full-hierarchy smoke (Plans 1-5 arc)"
```

---

## Task 3: Doc cross-link sweep

**Files:**
- Modify: `docs/continuation.md`
- Modify: `docs/refinement.md`
- Modify: `docs/outer-loop.md`

**Background.** Each doc should end with a "See also" block that links the other two + the spec. This implements CLAUDE.md's "every non-trivial concept reference must be one hop away from its neighbors" rule.

### Steps

- [ ] **Step 1: Append to `docs/continuation.md`**

At the end of the file:

```markdown
## See also

- `docs/refinement.md` — y-axis optimisation within a single run (auto-extracted gradient). Continuation is the cross-task analogue.
- `docs/outer-loop.md` — θ-axis optimisation over prompt artifacts. Runs per-experiment after Plan 4.
- `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` — the design this mechanism implements, §7.1–§7.4.
- `spec/versions/1.0/validation-rules.md` — R37 (continuation input non-emptiness).
```

- [ ] **Step 2: Append to `docs/refinement.md`**

At the end of the file:

```markdown
## See also

- `docs/continuation.md` — y-axis carry-over across tasks (user-feedback gradient). Related but distinct from refinement's auto-gradient within one run.
- `docs/outer-loop.md` — θ-axis optimisation. Now per-experiment (decision β).
- `packages/awp-runtime/src/awp/refinement/loop.py` — `RefinementLoop` implementation.
- After Plan 4: use `awp refine --target <exp>:<task>` to attach sessions under `<task>/refinements/session_<ts>/`.
```

- [ ] **Step 3: Append to `docs/outer-loop.md`**

At the end of the file:

```markdown
## See also

- `docs/refinement.md` — y-axis optimisation (a single run's deliverable).
- `docs/continuation.md` — y-axis carry-over across tasks.
- `packages/awp-runtime/src/awp/outer_loop/runner.py` — `SuiteRunner`.
- After Plan 4: use `awp optimize --target <exp>:<task> SUITE.yaml` to attach optimizations under `<task>/optimizations/suite_<ts>/`, using the per-experiment `<experiment>/outer_loop.db` (decision β).
```

- [ ] **Step 4: Drift gates**

```
python scripts/check_docs_drift.py && echo DRIFT_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 5: Commit**

```bash
git add docs/continuation.md docs/refinement.md docs/outer-loop.md
git commit -m "docs: cross-link continuation + refinement + outer-loop (Plan 6)"
```

---

## Task 4: CLAUDE.md — final hierarchy summary

**Files:**
- Modify: `CLAUDE.md` — APPEND ONLY, under existing UI section

**CRITICAL DISCIPLINE.** Plan 4 Task 7 gutted CLAUDE.md by mistake. Plan 6 MUST NOT repeat that. Absolute rule: only **append** a new sub-section at the END of the existing `## UI — Experiment/Task Hierarchy (Plan 5)` section. Do NOT touch any other content in CLAUDE.md.

- [ ] **Step 1: Append**

At the end of the existing `## UI — Experiment/Task Hierarchy (Plan 5)` block (or after the Development Commands block if the UI section is elsewhere), append:

```markdown
### Hierarchy — one-line map

```
Experiment (campaign)
  └── Task N (user intention: seed | continuation)
        └── Run M (role: seed | refine_iter | optimize_epoch_run)
              └── FINAL/     deliverable artifacts
  └── BEST/ per task         auto lowest-loss, user-overridable (reason: auto_loss|user_override)
  └── shared/                memory, dynamic_tools, skills — accumulate across tasks
  └── outer_loop.db          per-experiment artifact registry (after Plan 4)
```

| Plan | Landed |
|---|---|
| 1 | `ExperimentManifest` / `TaskManifest` models, DB tables, CLI CRUD |
| 2 | `awp run --target`, BEST finaliser, `awp task set-best` |
| 3 | Continuation loader (bundle + prefix), `awp run --target <cont>` |
| 4 | `awp refine --target`, `awp optimize --target`, `run_role` param |
| 5 | UI sidebar tree + Experiment/Task views + BEST override |
| 6 | `awp experiment purge-legacy`, cross-link sweep, full-arc smoke |

Normative rules: **R37** (continuation input non-emptiness; `spec/versions/1.0/validation-rules.md`).
```

- [ ] **Step 2: Drift gates**

```
python scripts/check_docs_drift.py && echo DRIFT_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md hierarchy summary (Plan 6)"
```

---

## Task 5: Final regression + mirror

- [ ] **Step 1: Full test suite**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ packages/awp-ui/server/tests/ -k "not e2e" 2>&1 | tail -10
```

Expected: all green. If any test is flaky (Task 2 noted the Plan 5 ASGI route tests may be slow) try once more; if still failing, document precisely what failed.

- [ ] **Step 2: Frontend build**

```
cd packages/awp-ui/frontend && npm run build 2>&1 | tail -5
cd ../../..
```

- [ ] **Step 3: Mirror sync**

```
rsync -a packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a packages/awp-ui/server/ reference/python/src/server/
```

- [ ] **Step 4: All three drift gates**

```
python scripts/check_mirror_drift.py && echo MIRROR_OK
python scripts/check_docs_drift.py && echo DOCS_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 5: Commit**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with Plan 6 (cleanup)"
```

- [ ] **Step 6: Final branch log**

```
git log --oneline --decorate -40
```

---

## Self-review

- `awp experiment purge-legacy` deletes legacy dirs + orphan `runs` rows, respects `--yes`, aborts on decline.
- `test_full_hierarchy_pipeline_smoke.py` passes — a single test covers all of Plans 1-5 using fake runs.
- Every architecture doc (`continuation.md`, `refinement.md`, `outer-loop.md`, `CLAUDE.md`) cross-links its neighbours.
- All three drift gates green. Full Python suite green. Frontend build clean.
- CLAUDE.md has the hierarchy summary appended — no restructuring happened.

## Plans 1-6 complete

Experiment-Task hierarchy is done end-to-end:
- Disk layout + DB schema + CLI (Plan 1)
- `awp run --target` + BEST finaliser (Plan 2)
- Continuation loader (Plan 3)
- Refine/Optimize under task (Plan 4)
- UI hierarchy with loss curves + BEST override (Plan 5)
- Purge-legacy + cross-links + full-arc smoke (Plan 6)

For real-LLM coverage, the existing `e2e` tag (`pytest -m e2e`) plus the new `awp run --target` path together give a deterministic E2E for an experiment-task-continuation run.
