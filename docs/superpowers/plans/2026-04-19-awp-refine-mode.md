# AWP Refinement Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second independent optimization mode `awp refine` that iteratively refines a completed run's deliverable using critique + gate + eval signals as the gradient — orthogonal to the existing outer-loop SGD over prompt artifacts.

**Architecture:** New package `packages/awp-runtime/src/awp/refinement/` wraps the existing `DelegationLoopRunner` via `AgentWorkflow`. Each refinement iteration is a standalone experiment linked to the prior iteration via `parent_run_id`. The gradient is extracted deterministically from `run_completion.json` + `events.jsonl` and injected as a prefix into only the first manager PLAN call.

**Tech Stack:** Python 3.10+, Pydantic, `AgentWorkflow` (awp-runtime), existing `compute_run_loss` (awp.outer_loop.loss), existing `DelegationLoopRunner`, Click-based `awp` CLI.

**E2E-Driven Discipline:** The E2E test file is created in Task 1 as a red scaffold. Every subsequent task has an **E2E Progress** acceptance line describing which E2E assertion it newly satisfies or which failure mode it removes. No task is complete until its E2E progress line is verified.

**Design Spec:** `docs/superpowers/specs/2026-04-19-awp-refine-mode-design.md`

---

## Scope Update — 2026-04-19 (post-writing-plans, per user directive)

Four overrides to the original plan, captured verbatim from the user handoff:

1. **Commit target: `main`.** No feature branch, no worktree. Each per-task commit lands directly on `main`.
2. **No `git push` until the user explicitly green-lights it** after the full implementation plus real-LLM E2E (Task 15) is production-ready. Commits accumulate locally.
3. **UI integration added.** Refinement mode must be usable end-to-end from `awp-ui` (backend endpoint + frontend trigger + session history). Specs for **Task 16** (UI backend) and **Task 17** (UI frontend) are appended at the end of this document.
4. **README "Key Features" link.** `README.md` must carry a link to `docs/refinement.md` under a `## Key Features` section. Added as **Task 18** at the end of this document. Task 11's one-paragraph README mention is superseded by Task 18; drop Step 4 of Task 11.

Additionally: **Task -1** commits the design spec (`docs/superpowers/specs/...`) and this plan file (`docs/superpowers/plans/...`) to `main` as the very first commit, so the subagent workflow has a traceable paper trail.

---

## Prerequisites

- Working tree on `main` (or a feature branch off `main`).
- `pytest packages/awp-core/tests/ packages/awp-runtime/tests/` green before starting.
- `scripts/check_docs_drift.py`, `scripts/check_sync_coverage.py`, `scripts/check_mirror_drift.py` all exit 0 before starting.
- OpenRouter API key available via `~/.awp/.env` or `OPENROUTER_API_KEY` env var (needed only for Task 15).

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `packages/awp-runtime/src/awp/refinement/__init__.py` | Public API exports: `RefinementLoop`, `RefinementGradient`, `RefinementResult`, `RefinementIteration` |
| `packages/awp-runtime/src/awp/refinement/gradient.py` | Pydantic `RefinementGradient` model, `extract_gradient()` from prior run artifacts, `render_refinement_prefix()` deterministic template |
| `packages/awp-runtime/src/awp/refinement/seed.py` | `prepare_iteration_workspace()` — hard-link/copy fallback of prior `FINAL/` into next iteration's `input/` |
| `packages/awp-runtime/src/awp/refinement/budget.py` | `budget_for_iteration()` — deterministic halving of seed budget with floor clamps |
| `packages/awp-runtime/src/awp/refinement/session.py` | `RefinementSession` dataclass, sidecar JSON writer for `refinement_sessions/<ts>.json`, `BEST/` pointer writer with manifest + hard-link/copy |
| `packages/awp-runtime/src/awp/refinement/loop.py` | `RefinementLoop` orchestrator — stop-condition state machine, best-iteration tracking, R36 enforcement, calls into `AgentWorkflow` per iteration |
| `packages/awp-runtime/tests/refinement/__init__.py` | Empty test package marker |
| `packages/awp-runtime/tests/refinement/conftest.py` | Shared fixtures: synthetic `run_completion.json` + `events.jsonl` builders |
| `packages/awp-runtime/tests/refinement/test_gradient.py` | Gradient extraction + prefix rendering unit tests |
| `packages/awp-runtime/tests/refinement/test_seed.py` | Workspace preparation unit tests (hard-link, copy fallback, clean state) |
| `packages/awp-runtime/tests/refinement/test_budget.py` | Budget scaling math with floor clamps |
| `packages/awp-runtime/tests/refinement/test_session.py` | Sidecar + BEST pointer writers |
| `packages/awp-runtime/tests/refinement/test_loop.py` | Loop orchestration with stubbed `AgentWorkflow` factory — stop conditions, best tracking, R36 abort |
| `packages/awp-runtime/tests/refinement/test_cli.py` | `awp refine` CLI integration with stubbed workflow |
| `packages/awp-runtime/tests/e2e/test_e2e_refinement.py` | Real-LLM E2E (Task 1 scaffold; finalized in Task 15) |
| `docs/refinement.md` | Authoritative protocol doc: data flow, stop conditions, R36, storage model |

### Modified files

| Path | Change |
|------|--------|
| `packages/awp-runtime/src/awp/data/workflow.py` | Add `manager_prompt_prefix`, `parent_run_id`, `tags` kwargs; pass to `DelegationLoopRunner`; surface in `run_completion.json` via runner |
| `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py` | Accept `manager_prompt_prefix` / `parent_run_id` / `tags`; inject prefix into first iteration's user message only; write fields into `run_completion.json` |
| `packages/awp-core/src/awp/cli.py` | Register `refine` subcommand |
| `CLAUDE.md` | Add "Refinement Mode" to Key Protocols, `awp refine` to Development Commands, sync-table row for refinement changes |
| `docs/e2e.md` | Add `refinement` tag to tag list |
| `README.md` | One-paragraph mention of refinement mode |
| `README_NERD.md` | Same, with θ/y framing |
| `skill/SKILL.md` | `awp refine` in Commands Reference + when-to-recommend note |
| `spec/versions/1.0/validation-rules.md` | Insert R36 after R35 |
| `spec/versions/1.0/spec.md` | Cross-reference R36 if the spec body references R35 |
| `reference/python/src/awp/refinement/**` | Mirror of new `packages/awp-runtime/src/awp/refinement/` tree (Task 14) |
| `reference/python/src/awp/data/workflow.py`, `reference/python/src/awp/runtime/delegation_loop_runner.py`, `reference/python/src/awp/cli.py` | Mirror of modifications (Task 14) |

---

## Task 0: Prerequisite — Audit and thread `parent_run_id` + `tags` through `run_completion.json`

**Why first:** The design requires iterations to be linked via `parent_run_id`. A repo-wide grep confirmed this field does not exist anywhere yet. Without it, all later tasks break — the E2E's parent-chain assertion would be untestable.

**Files:**
- Modify: `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`
- Modify: `packages/awp-runtime/src/awp/data/workflow.py`
- Test: `packages/awp-runtime/tests/test_run_completion_metadata.py` (new)

- [ ] **Step 1: Write the failing test**

Create `packages/awp-runtime/tests/test_run_completion_metadata.py`:

```python
"""Verify AgentWorkflow threads parent_run_id and tags into run_completion.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from awp.data.workflow import AgentWorkflow


def test_agentworkflow_accepts_parent_run_id_and_tags(tmp_path: Path) -> None:
    wf = AgentWorkflow(
        inputs={},
        task="trivial",
        model="openai/gpt-5-mini",
        output_dir=str(tmp_path),
        parent_run_id="run_seed_123",
        tags=["refinement", "refine-iter-1"],
        max_loops=1,
        max_total_tokens=1000,
        max_wall_time=30,
    )
    assert wf.parent_run_id == "run_seed_123"
    assert wf.tags == ["refinement", "refine-iter-1"]


def test_delegation_loop_runner_writes_parent_run_id_into_completion(tmp_path: Path) -> None:
    """Stub-level test: DelegationLoopRunner persists parent_run_id + tags."""
    from awp.models.orchestration import (
        DelegationBudget,
        DelegationLoopConfig,
        DelegationLoopModels,
        WorkerPolicy,
        WorkerPolicyEnforced,
    )
    from awp.models.capabilities import SandboxConfig
    from awp.runtime.delegation_loop_runner import DelegationLoopRunner
    from awp.runtime.tools import ToolRegistry

    (tmp_path / "agents" / "manager").mkdir(parents=True)
    (tmp_path / "agents" / "manager" / "system_prompt.md").write_text("stub", encoding="utf-8")

    cfg = DelegationLoopConfig(
        manager="agents/manager",
        models=DelegationLoopModels(manager="openai/gpt-5-mini", worker="openai/gpt-5-mini"),
        budget=DelegationBudget(max_loops=1, max_total_workers=1, max_total_tokens=100, max_wall_time=5, max_tool_calls=1, max_depth=1),
        worker_policy=WorkerPolicy(enforced=WorkerPolicyEnforced()),
    )
    runner = DelegationLoopRunner(
        workflow_dir=tmp_path,
        config=cfg,
        tool_registry=ToolRegistry(workflow_dir=tmp_path),
        manager_model="openai/gpt-5-mini",
        worker_model="openai/gpt-5-mini",
        parent_run_id="run_seed_123",
        tags=["refinement", "refine-iter-1"],
    )
    # Stub the actual loop run — we only care about the metadata fields.
    with patch.object(runner, "_run_iteration_loop", return_value={"confidence": 0.5}):
        runner.run("trivial")

    run_completion_path = next(tmp_path.rglob("run_completion.json"), None)
    assert run_completion_path is not None, "run_completion.json must be written"
    data = json.loads(run_completion_path.read_text(encoding="utf-8"))
    assert data.get("parent_run_id") == "run_seed_123"
    assert data.get("tags") == ["refinement", "refine-iter-1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest packages/awp-runtime/tests/test_run_completion_metadata.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'parent_run_id'`.

- [ ] **Step 3: Add parameters to `AgentWorkflow.__init__`**

In `packages/awp-runtime/src/awp/data/workflow.py`, add to the keyword arguments after `experiment_context: str | None = None,` (around line 144):

```python
        # Refinement-mode plumbing
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        manager_prompt_prefix: str | None = None,
```

And in the `__init__` body, after `self.experiment_context = experiment_context` (around line 209), add:

```python
        # Refinement-mode plumbing
        self.parent_run_id = parent_run_id
        self.tags = tags or []
        self.manager_prompt_prefix = manager_prompt_prefix
```

Then in `_execute`, where `DelegationLoopRunner` is constructed (around line 418–427), pass the new kwargs:

```python
        runner = DelegationLoopRunner(
            workflow_dir=workspace_dir,
            config=config,
            tool_registry=tool_registry,
            manager_model=self.model,
            worker_model=self.worker_model,
            eval_config=eval_cfg,
            llm_client=eval_llm,
            profile=self.profile,
            parent_run_id=self.parent_run_id,
            tags=self.tags,
            manager_prompt_prefix=self.manager_prompt_prefix,
        )
```

- [ ] **Step 4: Add parameters to `DelegationLoopRunner.__init__`**

In `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`, locate the `__init__` signature and add three new keyword arguments at the end:

```python
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        manager_prompt_prefix: str | None = None,
```

Store them on the instance:

```python
        self._parent_run_id = parent_run_id
        self._tags = list(tags) if tags else []
        self._manager_prompt_prefix = manager_prompt_prefix
```

Locate the `run_completion.json` write path (grep for `run_completion.json` in the file). In the dict that gets serialized, add:

```python
        completion_payload["parent_run_id"] = self._parent_run_id
        completion_payload["tags"] = list(self._tags)
```

If the write happens in multiple places (normal path + finalizer), add the two lines in both.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest packages/awp-runtime/tests/test_run_completion_metadata.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Regression sweep**

Run: `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" -x`
Expected: All existing tests PASS. New parameters default to `None` / `[]` so nothing else should change.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-runtime/src/awp/data/workflow.py \
        packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py \
        packages/awp-runtime/tests/test_run_completion_metadata.py
git commit -m "$(cat <<'EOF'
feat(runtime): thread parent_run_id + tags + manager_prompt_prefix through AgentWorkflow

Prereq for refinement mode: iterations need to be linkable via
parent_run_id and filterable via tags. manager_prompt_prefix carries
the refinement gradient into the first PLAN.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**E2E Progress:** Plumbing is in place so the E2E test (Task 1) will be able to assert `parent_run_id` on each iteration. No E2E step is executable yet.

---

## Task 1: E2E scaffold — create the failing E2E test file

**Why:** Per user mandate, every subsequent task advances this test. The scaffold is created first (red) so each task has a concrete target.

**Files:**
- Create: `packages/awp-runtime/tests/e2e/test_e2e_refinement.py`

- [ ] **Step 1: Write the E2E scaffold (initially skipped; individual steps un-skip as implemented)**

Create `packages/awp-runtime/tests/e2e/test_e2e_refinement.py`:

```python
"""E2E test for awp refine — the north star for the refinement implementation plan.

This test is progressively un-skipped as tasks land. Each task's
'E2E Progress' acceptance line maps to a concrete assertion or a
removed `pytest.skip`.

Tags: ["e2e", "refinement", "critique"]
Budget: >=25 loops / 3M tokens / 1h wall-time across the whole session.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


E2E_BASE = Path("/tmp/awp-experiments/e2e-refinement")
SEED_RUN_DIR = E2E_BASE / "seed"


def _has_llm_key() -> bool:
    return any(
        os.environ.get(k)
        for k in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    )


@pytest.fixture(scope="module")
def seed_run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Produce (or reuse) a seed run that lands at `partial` with a critique-detectable defect.

    Task 15 replaces this body with a real AgentWorkflow run. For now
    the fixture raises so sub-tests skip cleanly until wired up.
    """
    pytest.skip("seed run fixture not yet wired (Task 15)")


# -- Assertions the plan's tasks light up one by one --


def test_e2e_seed_run_has_expected_artifacts(seed_run_dir: Path) -> None:
    """Baseline: seed completed with FINAL/ and a non-trivial loss."""
    assert (seed_run_dir / "run_completion.json").exists()
    assert (seed_run_dir / "FINAL").exists()
    assert any((seed_run_dir / "FINAL").iterdir())


def test_e2e_gradient_is_non_empty(seed_run_dir: Path) -> None:
    """After Task 2: gradient extraction finds at least one defect/rejection/eval delta."""
    from awp.refinement.gradient import extract_gradient

    gradient = extract_gradient(seed_run_dir)
    assert gradient.is_non_empty(), f"seed gradient was empty: {gradient}"


def test_e2e_refinement_prefix_includes_defects(seed_run_dir: Path) -> None:
    """After Task 3: prefix template renders with defect bullets."""
    from awp.refinement.gradient import extract_gradient, render_refinement_prefix

    gradient = extract_gradient(seed_run_dir)
    prefix = render_refinement_prefix(gradient)
    assert "REFINEMENT CONTEXT" in prefix
    assert "Objective:" in prefix


def test_e2e_seed_workspace_prepared_for_iteration(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    """After Task 4: workspace prep copies/hard-links FINAL into input/."""
    from awp.refinement.seed import prepare_iteration_workspace

    workspace = tmp_path / "iter_1"
    prepare_iteration_workspace(
        workspace_dir=workspace,
        prior_final_dir=seed_run_dir / "FINAL",
    )
    assert (workspace / "input").exists()
    assert any((workspace / "input").iterdir())


def test_e2e_budget_halved_per_iteration() -> None:
    """After Task 5: budget scaler halves counts with floor clamps."""
    from awp.refinement.budget import budget_for_iteration

    out = budget_for_iteration(
        seed_budget={
            "max_loops": 20,
            "max_total_workers": 40,
            "max_total_tokens": 1_000_000,
            "max_wall_time": 3600,
            "max_depth": 4,
        },
        observed_wall_time=1800,
    )
    assert out["max_loops"] == 10
    assert out["max_total_workers"] == 20
    assert out["max_total_tokens"] == 500_000
    assert out["max_wall_time"] == 900
    assert out["max_depth"] == 4


def test_e2e_manager_prefix_reaches_first_iteration_user_message(
    seed_run_dir: Path, tmp_path: Path
) -> None:
    """After Task 6: DelegationLoopRunner injects prefix into iteration-1 user message only."""
    pytest.skip("unit-verified in Task 6; this E2E hook is covered by test_loop.py")


def test_e2e_iteration_has_parent_run_id_chain(seed_run_dir: Path) -> None:
    """After Task 8: iteration runs carry parent_run_id pointing at seed or prior iter."""
    session = _load_latest_session(seed_run_dir)
    iter1_run_dir = _find_iteration_run_dir(session["iterations"][0]["run_id"])
    rc = json.loads((iter1_run_dir / "run_completion.json").read_text())
    assert rc["parent_run_id"] == session["seed_run_id"]
    if len(session["iterations"]) >= 2:
        iter2_run_dir = _find_iteration_run_dir(session["iterations"][1]["run_id"])
        rc2 = json.loads((iter2_run_dir / "run_completion.json").read_text())
        assert rc2["parent_run_id"] == session["iterations"][0]["run_id"]


def test_e2e_best_pointer_and_session_sidecar_exist(seed_run_dir: Path) -> None:
    """After Task 9: seed/BEST/ and seed/refinement_sessions/<ts>.json are written."""
    assert (seed_run_dir / "BEST" / "manifest.json").exists()
    sessions = list((seed_run_dir / "refinement_sessions").glob("*.json"))
    assert sessions, "at least one session sidecar required"


def test_e2e_r36_aborts_on_empty_gradient(tmp_path: Path) -> None:
    """After Task 10: a completed-perfect seed yields 'nothing to refine' exit 0."""
    from awp.refinement.loop import RefinementLoop, NothingToRefine

    fake_seed = tmp_path / "perfect_seed"
    fake_seed.mkdir()
    (fake_seed / "FINAL").mkdir()
    (fake_seed / "run_completion.json").write_text(
        json.dumps({
            "status": "complete",
            "confidence": 1.0,
            "critique": {"defects": []},
            "evaluation": {"per_metric": {}, "total_score": 1.0},
        }),
        encoding="utf-8",
    )
    (fake_seed / "events.jsonl").write_text("", encoding="utf-8")

    loop = RefinementLoop(seed_run_dir=fake_seed)
    with pytest.raises(NothingToRefine):
        loop.run(iterations=2)


def test_e2e_cli_invocation_produces_session(seed_run_dir: Path) -> None:
    """After Task 11: `awp refine <seed>` creates a new session + BEST/."""
    # Verified in test_cli.py with a stubbed workflow. The real-LLM
    # assertion lives below in test_e2e_final_refinement_reduces_loss.
    pass


def test_e2e_final_refinement_reduces_loss(seed_run_dir: Path) -> None:
    """Task 15 terminal assertion: BEST/ has strictly lower loss than seed."""
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")
    from awp.outer_loop.loss import compute_run_loss

    session = _load_latest_session(seed_run_dir)
    best_iter_run_id = session["iterations"][session["best_iter"] - 1]["run_id"]
    best_run_dir = _find_iteration_run_dir(best_iter_run_id)

    seed_loss = compute_run_loss(seed_run_dir).total
    best_loss = compute_run_loss(best_run_dir).total
    assert best_loss < seed_loss, f"refinement did not reduce loss: {best_loss} >= {seed_loss}"


# -- Helpers (stub until Task 15 fills them in) --


def _load_latest_session(seed_run_dir: Path) -> dict:
    sessions = sorted((seed_run_dir / "refinement_sessions").glob("*.json"))
    assert sessions, "no refinement session found"
    return json.loads(sessions[-1].read_text(encoding="utf-8"))


def _find_iteration_run_dir(run_id: str) -> Path:
    """Locate an iteration's run directory by run_id.

    Implemented in Task 15 once the experiment root layout is concrete.
    """
    roots = [Path("/tmp/awp-experiments"), Path.home() / ".awp" / "experiments"]
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("run_completion.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("run_id") == run_id:
                return p.parent
    raise FileNotFoundError(f"no run dir for {run_id}")
```

- [ ] **Step 2: Run the E2E file — confirm every test fails or skips cleanly**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py -v --no-header 2>&1 | head -80`
Expected: all tests either FAIL with `ModuleNotFoundError: No module named 'awp.refinement'` or SKIP with the fixture message. **No error outside the expected import/skip pattern.**

- [ ] **Step 3: Commit**

```bash
git add packages/awp-runtime/tests/e2e/test_e2e_refinement.py
git commit -m "$(cat <<'EOF'
test(e2e): add red scaffold for refinement mode

E2E is the north star — subsequent tasks un-skip its assertions
one by one. Currently all tests fail on missing awp.refinement
module, as intended.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**E2E Progress:** The E2E file exists. All assertions fail with the expected "missing module" errors — this is the baseline the remaining tasks close.

---

## Task 2: Gradient extraction — `RefinementGradient` model + `extract_gradient()`

**Files:**
- Create: `packages/awp-runtime/src/awp/refinement/__init__.py`
- Create: `packages/awp-runtime/src/awp/refinement/gradient.py`
- Create: `packages/awp-runtime/tests/refinement/__init__.py`
- Create: `packages/awp-runtime/tests/refinement/conftest.py`
- Create: `packages/awp-runtime/tests/refinement/test_gradient.py`

- [ ] **Step 1: Create package markers**

```bash
mkdir -p packages/awp-runtime/src/awp/refinement
mkdir -p packages/awp-runtime/tests/refinement
touch packages/awp-runtime/src/awp/refinement/__init__.py
touch packages/awp-runtime/tests/refinement/__init__.py
```

- [ ] **Step 2: Write the shared test fixture**

Create `packages/awp-runtime/tests/refinement/conftest.py`:

```python
"""Shared fixtures for refinement tests — synthetic prior-run artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def synthetic_run_dir(tmp_path: Path) -> Path:
    """A prior-run directory with populated critique, gates, and eval signals."""
    run = tmp_path / "run_seed"
    (run / "FINAL").mkdir(parents=True)
    (run / "FINAL" / "paper.md").write_text("# Draft paper (missing section 3)\n", encoding="utf-8")

    (run / "run_completion.json").write_text(
        json.dumps({
            "run_id": "run_seed",
            "status": "partial",
            "confidence": 0.55,
            "task": "write a bilingual paper",
            "critique": {
                "defects": [
                    {"summary": "Section 3 missing required citations", "severity": "high"},
                    {"summary": "German abstract is shorter than required", "severity": "medium"},
                ]
            },
            "evaluation": {
                "per_metric": {
                    "structural_completeness": 0.60,
                    "factual_accuracy": 0.80,
                    "bilingual_coverage": 0.50,
                },
                "thresholds": {
                    "structural_completeness": 0.85,
                    "factual_accuracy": 0.90,
                    "bilingual_coverage": 0.75,
                },
                "total_score": 0.63,
            },
        }),
        encoding="utf-8",
    )

    events = [
        {"type": "gate.reject", "gate": "deliverable_presence", "reason": "section_3_incomplete", "ts": "2026-04-19T10:00:00Z"},
        {"type": "gate.reject", "gate": "eval", "reason": "bilingual_coverage_below_threshold", "ts": "2026-04-19T10:02:00Z"},
        {"type": "worker.spawn", "ts": "2026-04-19T10:03:00Z"},
        {"type": "gate.reject", "gate": "structural_integrity", "reason": "abstract_too_short", "ts": "2026-04-19T10:05:00Z"},
        {"type": "gate.reject", "gate": "deliverable", "reason": "missing_references", "ts": "2026-04-19T10:07:00Z"},
    ]
    (run / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    return run


@pytest.fixture
def perfect_run_dir(tmp_path: Path) -> Path:
    """A prior run with no defects, no rejections, all eval metrics above threshold."""
    run = tmp_path / "run_perfect"
    (run / "FINAL").mkdir(parents=True)
    (run / "FINAL" / "paper.md").write_text("# Perfect\n", encoding="utf-8")

    (run / "run_completion.json").write_text(
        json.dumps({
            "run_id": "run_perfect",
            "status": "complete",
            "confidence": 0.95,
            "task": "trivial",
            "critique": {"defects": []},
            "evaluation": {
                "per_metric": {"quality": 0.95},
                "thresholds": {"quality": 0.80},
                "total_score": 0.95,
            },
        }),
        encoding="utf-8",
    )
    (run / "events.jsonl").write_text("", encoding="utf-8")
    return run
```

- [ ] **Step 3: Write the failing test**

Create `packages/awp-runtime/tests/refinement/test_gradient.py`:

```python
"""Unit tests for gradient extraction and prefix rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.refinement.gradient import (
    RefinementGradient,
    extract_gradient,
    render_refinement_prefix,
)


def test_extract_gradient_populates_all_sections(synthetic_run_dir: Path) -> None:
    gradient = extract_gradient(synthetic_run_dir)

    assert gradient.prior_run_id == "run_seed"
    assert len(gradient.defects) == 2
    assert gradient.defects[0].severity == "high"

    # Only last 3 gate rejections retained.
    assert len(gradient.rejected_gates) == 3
    assert gradient.rejected_gates[0].gate == "eval"  # most recent first 3 from events
    assert {g.gate for g in gradient.rejected_gates} == {
        "eval",
        "structural_integrity",
        "deliverable",
    }

    # Eval deltas include only metrics below their thresholds.
    assert "structural_completeness" in gradient.eval_deltas
    assert gradient.eval_deltas["structural_completeness"] == pytest.approx(0.25)
    assert "factual_accuracy" in gradient.eval_deltas
    assert gradient.eval_deltas["factual_accuracy"] == pytest.approx(0.10)
    assert "bilingual_coverage" in gradient.eval_deltas
    # No negative deltas.
    assert all(v > 0 for v in gradient.eval_deltas.values())


def test_extract_gradient_from_perfect_run_is_empty(perfect_run_dir: Path) -> None:
    gradient = extract_gradient(perfect_run_dir)
    assert gradient.defects == []
    assert gradient.rejected_gates == []
    assert gradient.eval_deltas == {}
    assert not gradient.is_non_empty()


def test_extract_gradient_tolerates_missing_sections(tmp_path: Path) -> None:
    run = tmp_path / "minimal"
    run.mkdir()
    (run / "FINAL").mkdir()
    (run / "run_completion.json").write_text(
        json.dumps({"run_id": "minimal", "status": "failed"}),
        encoding="utf-8",
    )
    (run / "events.jsonl").write_text("", encoding="utf-8")

    gradient = extract_gradient(run)  # must not raise
    assert gradient.defects == []
    assert gradient.rejected_gates == []
    assert gradient.eval_deltas == {}


def test_extract_gradient_raises_on_missing_run_completion(tmp_path: Path) -> None:
    run = tmp_path / "no_run_completion"
    run.mkdir()
    with pytest.raises(FileNotFoundError):
        extract_gradient(run)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest packages/awp-runtime/tests/refinement/test_gradient.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'awp.refinement.gradient'`.

- [ ] **Step 5: Implement `gradient.py`**

Create `packages/awp-runtime/src/awp/refinement/gradient.py`:

```python
"""Gradient extraction from a prior run's artifacts.

The gradient is the deterministic signal that drives refinement: a
structured summary of what the prior run got wrong, built from:

* critique defects (``run_completion.json.critique.defects``),
* the last 3 gate rejections (``events.jsonl`` where ``type`` ==
  ``"gate.reject"``),
* eval metric deltas — for every metric whose observed score is below
  its configured threshold, ``gap = threshold - observed``.

An empty gradient (no defects, no rejections, no gaps) aborts the
refinement loop early (R36).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Defect(BaseModel):
    summary: str
    severity: str = "medium"
    evidence: str | None = None


class RejectedGate(BaseModel):
    gate: str
    reason: str
    ts: str | None = None


class RefinementGradient(BaseModel):
    prior_run_id: str
    prior_loss_total: float | None = None
    prior_raw_signals: dict[str, Any] = Field(default_factory=dict)
    defects: list[Defect] = Field(default_factory=list)
    rejected_gates: list[RejectedGate] = Field(default_factory=list)
    eval_deltas: dict[str, float] = Field(default_factory=dict)

    def is_non_empty(self) -> bool:
        return bool(self.defects or self.rejected_gates or self.eval_deltas)


def extract_gradient(prior_run_dir: Path) -> RefinementGradient:
    """Read the prior run and produce a structured gradient.

    Missing sections (no critique configured, no events, no eval) degrade
    gracefully to empty — they do not raise. Only a missing or malformed
    ``run_completion.json`` is a hard error.
    """
    rc_path = prior_run_dir / "run_completion.json"
    if not rc_path.exists():
        raise FileNotFoundError(f"run_completion.json not found in {prior_run_dir}")
    data = json.loads(rc_path.read_text(encoding="utf-8"))

    defects = [
        Defect(
            summary=str(d.get("summary", "")),
            severity=str(d.get("severity", "medium")),
            evidence=d.get("evidence"),
        )
        for d in (data.get("critique") or {}).get("defects", [])
        if d.get("summary")
    ]

    rejected_gates = _extract_last_rejections(prior_run_dir / "events.jsonl", limit=3)
    eval_deltas = _extract_eval_deltas(data.get("evaluation") or {})

    return RefinementGradient(
        prior_run_id=str(data.get("run_id") or prior_run_dir.name),
        prior_loss_total=_safe_float(data.get("loss_total")),
        prior_raw_signals=_collect_raw_signals(data),
        defects=defects,
        rejected_gates=rejected_gates,
        eval_deltas=eval_deltas,
    )


def _extract_last_rejections(events_path: Path, limit: int) -> list[RejectedGate]:
    if not events_path.exists():
        return []
    rejects: list[RejectedGate] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "gate.reject" and ev.get("gate"):
            rejects.append(
                RejectedGate(
                    gate=str(ev["gate"]),
                    reason=str(ev.get("reason", "")),
                    ts=ev.get("ts"),
                )
            )
    return rejects[-limit:][::-1]  # most recent first


def _extract_eval_deltas(evaluation: dict[str, Any]) -> dict[str, float]:
    per_metric = evaluation.get("per_metric") or {}
    thresholds = evaluation.get("thresholds") or {}
    out: dict[str, float] = {}
    for name, observed in per_metric.items():
        try:
            o = float(observed)
        except (TypeError, ValueError):
            continue
        t = thresholds.get(name)
        try:
            t_f = float(t) if t is not None else None
        except (TypeError, ValueError):
            t_f = None
        if t_f is not None and o < t_f:
            out[name] = round(t_f - o, 4)
    return out


def _collect_raw_signals(data: dict[str, Any]) -> dict[str, Any]:
    signals = {}
    ev = data.get("evaluation") or {}
    if "total_score" in ev:
        signals["eval_score"] = ev["total_score"]
    if "confidence" in data:
        signals["confidence"] = data["confidence"]
    crit = data.get("critique") or {}
    if "defects" in crit:
        signals["critique_defect_count"] = len(crit["defects"])
    return signals


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def render_refinement_prefix(gradient: RefinementGradient) -> str:
    """Deterministic template. Empty sections are omitted from the output."""
    lines: list[str] = []
    lines.append("## REFINEMENT CONTEXT")
    lines.append("")
    lines.append("You are refining an existing deliverable for the task below.")
    lines.append("")
    lines.append("Prior deliverable is available at: input/")
    if gradient.prior_loss_total is not None:
        lines.append(f"Prior loss: {gradient.prior_loss_total:.3f}")
    if gradient.prior_raw_signals:
        for k, v in gradient.prior_raw_signals.items():
            lines.append(f"  - {k}: {v}")
    lines.append("")

    if gradient.defects:
        lines.append("Defects identified by prior critique:")
        for d in gradient.defects:
            lines.append(f"  - [{d.severity}] {d.summary}")
        lines.append("")

    if gradient.rejected_gates:
        lines.append("Rejected gates in prior run:")
        for g in gradient.rejected_gates:
            lines.append(f"  - {g.gate}: {g.reason}")
        lines.append("")

    if gradient.eval_deltas:
        lines.append("Metric gaps to close:")
        for metric, gap in gradient.eval_deltas.items():
            lines.append(f"  - {metric}: +{gap:.2f} needed")
        lines.append("")

    lines.append("Objective: produce an improved deliverable that reduces total loss.")
    lines.append("Preserve what works; fix what the gradient identifies above.")
    lines.append("Do not rewrite from scratch — iterate on the prior deliverable in input/.")
    return "\n".join(lines)
```

- [ ] **Step 6: Export from package `__init__.py`**

Edit `packages/awp-runtime/src/awp/refinement/__init__.py`:

```python
"""AWP Refinement Mode — task-local iterative refinement of a deliverable."""

from awp.refinement.gradient import (
    Defect,
    RefinementGradient,
    RejectedGate,
    extract_gradient,
    render_refinement_prefix,
)

__all__ = [
    "Defect",
    "RefinementGradient",
    "RejectedGate",
    "extract_gradient",
    "render_refinement_prefix",
]
```

- [ ] **Step 7: Run unit tests**

Run: `pytest packages/awp-runtime/tests/refinement/test_gradient.py -v`
Expected: 4 tests PASS.

- [ ] **Step 8: Re-run E2E — two more assertions now green**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py::test_e2e_gradient_is_non_empty packages/awp-runtime/tests/e2e/test_e2e_refinement.py::test_e2e_refinement_prefix_includes_defects -v 2>&1 | tail -20`
Expected: both SKIP with "seed run fixture not yet wired (Task 15)". **The module-not-found errors are gone** — the fixtures now resolve cleanly, which is the progress for this step.

- [ ] **Step 9: Commit**

```bash
git add packages/awp-runtime/src/awp/refinement/ packages/awp-runtime/tests/refinement/
git commit -m "$(cat <<'EOF'
feat(refinement): gradient extraction + prefix rendering

Task 2 of refinement mode. Deterministic extraction from
run_completion.json + events.jsonl; prefix template omits empty
sections.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**E2E Progress:** `awp.refinement.gradient` module resolves. E2E assertions `test_e2e_gradient_is_non_empty` and `test_e2e_refinement_prefix_includes_defects` now fail only at the fixture level, not at module import.

---

## Task 3: Seed workspace preparation — `seed.py`

**Files:**
- Create: `packages/awp-runtime/src/awp/refinement/seed.py`
- Create: `packages/awp-runtime/tests/refinement/test_seed.py`
- Modify: `packages/awp-runtime/src/awp/refinement/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-runtime/tests/refinement/test_seed.py`:

```python
"""Unit tests for iteration workspace preparation."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from awp.refinement.seed import prepare_iteration_workspace


def test_prepare_workspace_creates_input_from_prior_final(tmp_path: Path) -> None:
    prior_final = tmp_path / "seed" / "FINAL"
    prior_final.mkdir(parents=True)
    (prior_final / "paper.md").write_text("# Paper\n", encoding="utf-8")
    (prior_final / "nested" / "data.json").parent.mkdir()
    (prior_final / "nested" / "data.json").write_text("{}", encoding="utf-8")

    workspace = tmp_path / "iter_1"
    prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)

    assert (workspace / "input" / "paper.md").read_text(encoding="utf-8") == "# Paper\n"
    assert (workspace / "input" / "nested" / "data.json").exists()


def test_prepare_workspace_falls_back_to_copy_on_crossdevice(tmp_path: Path) -> None:
    prior_final = tmp_path / "seed" / "FINAL"
    prior_final.mkdir(parents=True)
    (prior_final / "a.txt").write_text("a", encoding="utf-8")

    workspace = tmp_path / "iter_1"

    original_link = os.link

    def fake_link(src, dst, *args, **kwargs):
        raise OSError(18, "Invalid cross-device link")

    with patch("awp.refinement.seed.os.link", side_effect=fake_link):
        prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)

    assert (workspace / "input" / "a.txt").read_text(encoding="utf-8") == "a"


def test_prepare_workspace_raises_when_prior_final_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "iter_1"
    with pytest.raises(FileNotFoundError):
        prepare_iteration_workspace(
            workspace_dir=workspace,
            prior_final_dir=tmp_path / "nonexistent",
        )


def test_prepare_workspace_refuses_nonempty_target(tmp_path: Path) -> None:
    prior_final = tmp_path / "seed" / "FINAL"
    prior_final.mkdir(parents=True)
    (prior_final / "a.txt").write_text("a", encoding="utf-8")

    workspace = tmp_path / "iter_1"
    (workspace / "input").mkdir(parents=True)
    (workspace / "input" / "stale.txt").write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        prepare_iteration_workspace(workspace_dir=workspace, prior_final_dir=prior_final)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest packages/awp-runtime/tests/refinement/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'awp.refinement.seed'`.

- [ ] **Step 3: Implement `seed.py`**

Create `packages/awp-runtime/src/awp/refinement/seed.py`:

```python
"""Workspace preparation for a refinement iteration.

Each iteration starts from a workspace seeded with the prior iteration's
``FINAL/`` tree — hard-linked where possible, falls back to copy on
cross-device or link-refusing filesystems. The seeded tree lives under
``<workspace>/input/`` so the manager's REFINEMENT CONTEXT prefix
(rendered in ``gradient.py``) can point at a stable path.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_iteration_workspace(
    *,
    workspace_dir: Path,
    prior_final_dir: Path,
) -> Path:
    """Create ``<workspace_dir>/input/`` containing the contents of
    ``prior_final_dir``. Returns the input directory path.

    Raises
    ------
    FileNotFoundError
        If ``prior_final_dir`` does not exist.
    FileExistsError
        If ``<workspace_dir>/input/`` already exists and is non-empty —
        the caller is responsible for cleanup to avoid accidental mixing.
    """
    if not prior_final_dir.exists():
        raise FileNotFoundError(f"prior_final_dir does not exist: {prior_final_dir}")

    input_dir = workspace_dir / "input"
    if input_dir.exists() and any(input_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty {input_dir}")

    input_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    link_mode = True
    for src in prior_final_dir.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(prior_final_dir)
        dst = input_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if link_mode:
            try:
                os.link(src, dst)
                continue
            except OSError as exc:
                logger.info(
                    "refinement.seed.hardlink_fallback reason=%s falling back to copy",
                    exc,
                )
                link_mode = False
        shutil.copy2(src, dst)

    return input_dir
```

- [ ] **Step 4: Export and run tests**

Append to `packages/awp-runtime/src/awp/refinement/__init__.py`:

```python
from awp.refinement.seed import prepare_iteration_workspace

__all__ = __all__ + ["prepare_iteration_workspace"]
```

Run: `pytest packages/awp-runtime/tests/refinement/test_seed.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Re-run E2E — one more unblock**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py::test_e2e_seed_workspace_prepared_for_iteration -v`
Expected: SKIP (fixture not yet wired). Import errors should be gone.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-runtime/src/awp/refinement/seed.py \
        packages/awp-runtime/src/awp/refinement/__init__.py \
        packages/awp-runtime/tests/refinement/test_seed.py
git commit -m "feat(refinement): iteration workspace seeding via hard-link + copy fallback

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** `awp.refinement.seed.prepare_iteration_workspace` is callable. `test_e2e_seed_workspace_prepared_for_iteration` fails only at fixture level.

---

## Task 4: Budget scaling helper — `budget.py`

**Files:**
- Create: `packages/awp-runtime/src/awp/refinement/budget.py`
- Create: `packages/awp-runtime/tests/refinement/test_budget.py`
- Modify: `packages/awp-runtime/src/awp/refinement/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-runtime/tests/refinement/test_budget.py`:

```python
"""Unit tests for refinement budget scaling."""

from __future__ import annotations

from awp.refinement.budget import budget_for_iteration


def test_halves_all_cost_dimensions() -> None:
    out = budget_for_iteration(
        seed_budget={
            "max_loops": 20,
            "max_total_workers": 40,
            "max_total_tokens": 1_000_000,
            "max_wall_time": 3600,
            "max_depth": 4,
            "max_tool_calls": 600,
        },
        observed_wall_time=1800,
    )
    assert out["max_loops"] == 10
    assert out["max_total_workers"] == 20
    assert out["max_total_tokens"] == 500_000
    assert out["max_tool_calls"] == 300
    # wall-time uses observed, not cap, halved.
    assert out["max_wall_time"] == 900
    # depth is structural, unchanged.
    assert out["max_depth"] == 4


def test_floor_clamps() -> None:
    out = budget_for_iteration(
        seed_budget={
            "max_loops": 1,
            "max_total_workers": 1,
            "max_total_tokens": 10,
            "max_wall_time": 30,
            "max_depth": 1,
            "max_tool_calls": 1,
        },
        observed_wall_time=10,
    )
    assert out["max_loops"] == 1
    assert out["max_total_workers"] == 1
    assert out["max_total_tokens"] == 5
    assert out["max_tool_calls"] == 1
    # wall-time floor 60s.
    assert out["max_wall_time"] == 60
    assert out["max_depth"] == 1


def test_observed_wall_time_zero_falls_back_to_cap() -> None:
    out = budget_for_iteration(
        seed_budget={
            "max_loops": 10,
            "max_total_workers": 10,
            "max_total_tokens": 1000,
            "max_wall_time": 600,
            "max_depth": 2,
            "max_tool_calls": 100,
        },
        observed_wall_time=0,
    )
    # No observed signal → scale from cap instead.
    assert out["max_wall_time"] == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest packages/awp-runtime/tests/refinement/test_budget.py -v`
Expected: FAIL with module import error.

- [ ] **Step 3: Implement `budget.py`**

Create `packages/awp-runtime/src/awp/refinement/budget.py`:

```python
"""Deterministic budget scaling for refinement iterations.

Counts and token caps are halved with ``ceil`` (floored at 1). Wall
time is halved from the observed wall time of the seed (not its cap),
floored at 60 s. Depth is structural and passes through unchanged.
"""

from __future__ import annotations

from math import ceil
from typing import Any

_COUNT_FIELDS = ("max_loops", "max_total_workers", "max_tool_calls")
_COUNT_FLOOR = 1
_TOKEN_FLOOR = 1
_WALL_FLOOR = 60


def budget_for_iteration(
    *,
    seed_budget: dict[str, Any],
    observed_wall_time: float,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in _COUNT_FIELDS:
        v = int(seed_budget.get(f, 0))
        out[f] = max(_COUNT_FLOOR, ceil(v * 0.5)) if v else _COUNT_FLOOR

    tokens = int(seed_budget.get("max_total_tokens", 0))
    out["max_total_tokens"] = max(_TOKEN_FLOOR, tokens // 2) if tokens else _TOKEN_FLOOR

    if observed_wall_time and observed_wall_time > 0:
        wall_seed = float(observed_wall_time)
    else:
        wall_seed = float(seed_budget.get("max_wall_time", 0))
    out["max_wall_time"] = max(_WALL_FLOOR, int(wall_seed * 0.5)) if wall_seed else _WALL_FLOOR

    out["max_depth"] = int(seed_budget.get("max_depth", 1))
    return out
```

- [ ] **Step 4: Export and run tests**

Append to `packages/awp-runtime/src/awp/refinement/__init__.py`:

```python
from awp.refinement.budget import budget_for_iteration

__all__ = __all__ + ["budget_for_iteration"]
```

Run: `pytest packages/awp-runtime/tests/refinement/test_budget.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Verify the E2E assertion for this task passes (no fixture dep)**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py::test_e2e_budget_halved_per_iteration -v`
Expected: **PASS** (this E2E assertion has no fixture dependency — first E2E test to flip green).

- [ ] **Step 6: Commit**

```bash
git add packages/awp-runtime/src/awp/refinement/budget.py \
        packages/awp-runtime/src/awp/refinement/__init__.py \
        packages/awp-runtime/tests/refinement/test_budget.py
git commit -m "feat(refinement): deterministic budget scaling with floor clamps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** First E2E assertion **green** — `test_e2e_budget_halved_per_iteration`.

---

## Task 5: Thread `manager_prompt_prefix` into the first iteration's user message

**Why:** Task 0 added the parameter on `DelegationLoopRunner` but it's not yet consumed. This task wires the prefix into the first PLAN's user message and verifies it does NOT leak into subsequent iterations.

**Files:**
- Modify: `packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py`
- Create: `packages/awp-runtime/tests/refinement/test_prefix_injection.py`

- [ ] **Step 1: Locate the injection point**

Run: `grep -n "user_message" packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py | head -20`

Find the first iteration's `user_message` construction — should be near the `_run_iteration_loop` entry or the first `_run_manager` call. The prefix must be prepended to the user message on iteration 1 only.

- [ ] **Step 2: Write the failing test**

Create `packages/awp-runtime/tests/refinement/test_prefix_injection.py`:

```python
"""Verify manager_prompt_prefix reaches iteration 1's user message only."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from awp.data.workflow import AgentWorkflow


def test_prefix_injected_into_iteration_1_user_message_only(tmp_path: Path, monkeypatch) -> None:
    captured_messages: list[tuple[int, str]] = []

    def fake_run_manager(self, iteration, system_prompt, user_message, *args, **kwargs):
        captured_messages.append((iteration, user_message))
        # Return a benign manager output to end the loop after iter 1.
        return {"decision": "COMPLETE", "confidence": 0.9, "result": {}}

    from awp.runtime.delegation_loop_runner import DelegationLoopRunner

    with patch.object(DelegationLoopRunner, "_run_manager", fake_run_manager):
        wf = AgentWorkflow(
            inputs={},
            task="do the thing",
            model="openai/gpt-5-mini",
            output_dir=str(tmp_path),
            manager_prompt_prefix="## REFINEMENT CONTEXT\nfix defect X",
            max_loops=2,
            max_total_tokens=1000,
            max_wall_time=30,
            critique_enabled=False,
        )
        wf.run()

    assert captured_messages, "manager was never called"
    iter1_msg = captured_messages[0][1]
    assert "REFINEMENT CONTEXT" in iter1_msg, "prefix missing from iter 1"
    # Subsequent messages must NOT re-include the prefix.
    for it, msg in captured_messages[1:]:
        assert "REFINEMENT CONTEXT" not in msg, f"prefix leaked into iteration {it}"


def test_no_prefix_leaves_message_unchanged(tmp_path: Path, monkeypatch) -> None:
    captured_messages: list[str] = []

    def fake_run_manager(self, iteration, system_prompt, user_message, *args, **kwargs):
        captured_messages.append(user_message)
        return {"decision": "COMPLETE", "confidence": 0.9, "result": {}}

    from awp.runtime.delegation_loop_runner import DelegationLoopRunner

    with patch.object(DelegationLoopRunner, "_run_manager", fake_run_manager):
        wf = AgentWorkflow(
            inputs={},
            task="do the thing",
            model="openai/gpt-5-mini",
            output_dir=str(tmp_path),
            max_loops=1,
            max_total_tokens=1000,
            max_wall_time=30,
            critique_enabled=False,
        )
        wf.run()

    assert captured_messages
    assert "REFINEMENT CONTEXT" not in captured_messages[0]
```

- [ ] **Step 3: Run the test — will fail with prefix missing**

Run: `pytest packages/awp-runtime/tests/refinement/test_prefix_injection.py -v`
Expected: `test_prefix_injected_into_iteration_1_user_message_only` FAILS because the prefix is never prepended.

- [ ] **Step 4: Modify `delegation_loop_runner.py` to prepend the prefix**

In `DelegationLoopRunner`, locate the place where the first iteration's user message is built (the `_guard_manager_context` call on line ~4974 shows where the final message is ready). Just before that call, add:

```python
        if iteration == 1 and self._manager_prompt_prefix:
            user_message = self._manager_prompt_prefix.rstrip() + "\n\n" + user_message
```

Exact location: find the first `user_message = self._guard_manager_context(...)` invocation in `_run_manager`. The prefix prepend goes on the line immediately before it.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest packages/awp-runtime/tests/refinement/test_prefix_injection.py -v`
Expected: 2 tests PASS.

- [ ] **Step 6: Regression sweep**

Run: `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" -x`
Expected: All pass. The `iteration == 1` guard and `self._manager_prompt_prefix is not None` check ensure no behavior change for existing callers.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py \
        packages/awp-runtime/tests/refinement/test_prefix_injection.py
git commit -m "feat(runtime): inject manager_prompt_prefix into iteration-1 user message

Prefix is prepended to the manager's user message on iteration 1 only.
Subsequent iterations get the vanilla message — the refinement intent
is already carried in plan + state by then.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** Prefix injection unit-verified. Covers the `test_e2e_manager_prefix_reaches_first_iteration_user_message` hook (which remains `skip` but is now unit-backed).

---

## Task 6: Session sidecar + BEST pointer writer — `session.py`

**Files:**
- Create: `packages/awp-runtime/src/awp/refinement/session.py`
- Create: `packages/awp-runtime/tests/refinement/test_session.py`
- Modify: `packages/awp-runtime/src/awp/refinement/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-runtime/tests/refinement/test_session.py`:

```python
"""Unit tests for RefinementSession sidecar + BEST pointer writers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.refinement.session import (
    RefinementIteration,
    RefinementSession,
    write_best_pointer,
    write_session_sidecar,
)


def _make_fake_iteration_dir(root: Path, run_id: str, payload: dict) -> Path:
    d = root / run_id
    (d / "FINAL").mkdir(parents=True)
    (d / "FINAL" / "paper.md").write_text(f"# Paper from {run_id}\n", encoding="utf-8")
    (d / "run_completion.json").write_text(json.dumps(payload), encoding="utf-8")
    return d


def test_session_sidecar_written_to_seed_dir(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    session = RefinementSession(
        session_id="refine_20260419T153000Z",
        seed_run_id="run_seed",
        started_at="2026-04-19T15:30:00Z",
        completed_at="2026-04-19T15:40:00Z",
        stop_reason="max_iterations",
        best_iter=2,
        iterations=[
            RefinementIteration(k=1, run_id="run_iter_1", loss=0.42, status="partial"),
            RefinementIteration(k=2, run_id="run_iter_2", loss=0.31, status="complete"),
        ],
    )
    path = write_session_sidecar(seed_run_dir=seed, session=session)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["best_iter"] == 2
    assert data["iterations"][1]["run_id"] == "run_iter_2"


def test_best_pointer_contains_manifest_and_winner_files(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    iterations_root = tmp_path / "iterations"
    win = _make_fake_iteration_dir(iterations_root, "run_iter_2", {"run_id": "run_iter_2"})

    write_best_pointer(
        seed_run_dir=seed,
        winning_run_dir=win,
        session_id="refine_20260419T153000Z",
        best_loss=0.31,
        seed_loss=0.47,
    )

    best = seed / "BEST"
    manifest = json.loads((best / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["best_run_id"] == "run_iter_2"
    assert manifest["best_loss"] == 0.31
    assert manifest["seed_loss"] == 0.47
    assert (best / "paper.md").read_text(encoding="utf-8") == "# Paper from run_iter_2\n"


def test_best_pointer_only_overwrites_on_improvement(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    iterations_root = tmp_path / "iterations"

    win_a = _make_fake_iteration_dir(iterations_root, "run_iter_A", {"run_id": "run_iter_A"})
    write_best_pointer(seed_run_dir=seed, winning_run_dir=win_a,
                       session_id="A", best_loss=0.30, seed_loss=0.50)

    win_b = _make_fake_iteration_dir(iterations_root, "run_iter_B", {"run_id": "run_iter_B"})
    write_best_pointer(seed_run_dir=seed, winning_run_dir=win_b,
                       session_id="B", best_loss=0.40, seed_loss=0.50)

    manifest = json.loads((seed / "BEST" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["best_run_id"] == "run_iter_A", "BEST must not regress"


def test_best_pointer_overwrites_when_new_loss_is_lower(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    iterations_root = tmp_path / "iterations"

    win_a = _make_fake_iteration_dir(iterations_root, "run_iter_A", {"run_id": "run_iter_A"})
    write_best_pointer(seed_run_dir=seed, winning_run_dir=win_a,
                       session_id="A", best_loss=0.40, seed_loss=0.50)

    win_b = _make_fake_iteration_dir(iterations_root, "run_iter_B", {"run_id": "run_iter_B"})
    write_best_pointer(seed_run_dir=seed, winning_run_dir=win_b,
                       session_id="B", best_loss=0.25, seed_loss=0.50)

    manifest = json.loads((seed / "BEST" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["best_run_id"] == "run_iter_B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest packages/awp-runtime/tests/refinement/test_session.py -v`
Expected: FAIL with module import error.

- [ ] **Step 3: Implement `session.py`**

Create `packages/awp-runtime/src/awp/refinement/session.py`:

```python
"""RefinementSession model + sidecar + BEST pointer writers.

Each refinement session produces exactly one sidecar file under
``<seed>/refinement_sessions/<session_id>.json`` and at most one update
to ``<seed>/BEST/`` — the latter only if the session's best loss is
strictly lower than the incumbent ``BEST/manifest.json.best_loss`` (or
if ``BEST/`` does not yet exist).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RefinementIteration:
    k: int
    run_id: str
    loss: float
    status: str


@dataclass
class RefinementSession:
    session_id: str
    seed_run_id: str
    started_at: str
    completed_at: str
    stop_reason: str
    best_iter: int
    iterations: list[RefinementIteration] = field(default_factory=list)


def write_session_sidecar(*, seed_run_dir: Path, session: RefinementSession) -> Path:
    sessions_dir = seed_run_dir / "refinement_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{session.session_id}.json"
    payload = asdict(session)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_best_pointer(
    *,
    seed_run_dir: Path,
    winning_run_dir: Path,
    session_id: str,
    best_loss: float,
    seed_loss: float,
) -> Path | None:
    """Update ``<seed>/BEST/`` if and only if ``best_loss`` is strictly
    lower than the incumbent.

    Returns the ``BEST/`` path if it was written, otherwise ``None``.
    """
    best_dir = seed_run_dir / "BEST"
    manifest_path = best_dir / "manifest.json"
    if manifest_path.exists():
        try:
            incumbent = json.loads(manifest_path.read_text(encoding="utf-8"))
            if float(incumbent.get("best_loss", float("inf"))) <= best_loss:
                logger.info(
                    "refinement.best.no_overwrite current=%.4f proposed=%.4f",
                    incumbent["best_loss"],
                    best_loss,
                )
                return None
        except (json.JSONDecodeError, OSError):
            logger.warning("refinement.best.manifest_unreadable — overwriting")

    winning_final = winning_run_dir / "FINAL"
    if not winning_final.exists():
        raise FileNotFoundError(f"winning run has no FINAL/: {winning_run_dir}")

    if best_dir.exists():
        shutil.rmtree(best_dir)
    best_dir.mkdir(parents=True)

    link_mode = True
    for src in winning_final.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(winning_final)
        dst = best_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if link_mode:
            try:
                os.link(src, dst)
                continue
            except OSError:
                link_mode = False
        shutil.copy2(src, dst)

    manifest = {
        "best_run_id": _read_run_id(winning_run_dir),
        "best_loss": best_loss,
        "seed_loss": seed_loss,
        "session_id": session_id,
        "winning_run_dir": str(winning_run_dir),
    }
    (best_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return best_dir


def _read_run_id(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if rc.exists():
        try:
            data = json.loads(rc.read_text(encoding="utf-8"))
            return str(data.get("run_id") or run_dir.name)
        except json.JSONDecodeError:
            pass
    return run_dir.name
```

- [ ] **Step 4: Export and run tests**

Append to `packages/awp-runtime/src/awp/refinement/__init__.py`:

```python
from awp.refinement.session import (
    RefinementIteration,
    RefinementSession,
    write_best_pointer,
    write_session_sidecar,
)

__all__ = __all__ + [
    "RefinementIteration",
    "RefinementSession",
    "write_best_pointer",
    "write_session_sidecar",
]
```

Run: `pytest packages/awp-runtime/tests/refinement/test_session.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-runtime/src/awp/refinement/session.py \
        packages/awp-runtime/src/awp/refinement/__init__.py \
        packages/awp-runtime/tests/refinement/test_session.py
git commit -m "feat(refinement): session sidecar + BEST pointer (no-regression)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** `awp.refinement.session` module resolves. E2E `test_e2e_best_pointer_and_session_sidecar_exist` will pass once Task 15's seed fixture writes them.

---

## Task 7: `RefinementLoop` orchestrator + stop conditions (stubbed workflow factory)

**Files:**
- Create: `packages/awp-runtime/src/awp/refinement/loop.py`
- Create: `packages/awp-runtime/tests/refinement/test_loop.py`
- Modify: `packages/awp-runtime/src/awp/refinement/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `packages/awp-runtime/tests/refinement/test_loop.py`:

```python
"""Unit tests for RefinementLoop orchestration — stubbed workflow factory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from awp.refinement.loop import (
    NothingToRefine,
    RefinementLoop,
    RefinementResult,
)


def _make_seed(tmp_path: Path, *, with_gradient: bool = True) -> Path:
    seed = tmp_path / "seed"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "paper.md").write_text("# seed\n", encoding="utf-8")
    critique = {"defects": [{"summary": "missing", "severity": "high"}]} if with_gradient else {"defects": []}
    eval_ = (
        {"per_metric": {"m1": 0.5}, "thresholds": {"m1": 0.9}, "total_score": 0.5}
        if with_gradient
        else {"per_metric": {"m1": 1.0}, "thresholds": {"m1": 0.5}, "total_score": 1.0}
    )
    (seed / "run_completion.json").write_text(
        json.dumps({
            "run_id": "run_seed",
            "status": "partial" if with_gradient else "complete",
            "confidence": 0.6 if with_gradient else 1.0,
            "task": "write a paper",
            "critique": critique,
            "evaluation": eval_,
        }),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


class StubWorkflow:
    """Stand-in for AgentWorkflow that writes a minimal run_completion.json."""

    def __init__(self, losses: list[float], statuses: list[str] | None = None):
        self._losses = iter(losses)
        self._statuses = iter(statuses or ["partial"] * len(losses))

    def __call__(self, *, task: str, inputs, initial_state, output_dir: Path,
                 parent_run_id, tags, manager_prompt_prefix, budget, model, worker_model):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "FINAL").mkdir(exist_ok=True)
        (output_dir / "FINAL" / "paper.md").write_text("# improved\n", encoding="utf-8")
        loss = next(self._losses)
        status = next(self._statuses)
        run_id = f"run_iter_{output_dir.name}"
        (output_dir / "run_completion.json").write_text(
            json.dumps({
                "run_id": run_id,
                "status": status,
                "confidence": 0.8,
                "parent_run_id": parent_run_id,
                "tags": tags,
                "loss_total": loss,
                "evaluation": {"total_score": 1.0 - loss, "per_metric": {}, "thresholds": {}},
            }),
            encoding="utf-8",
        )
        (output_dir / "events.jsonl").write_text("", encoding="utf-8")
        # Patch compute_run_loss via monkeypatch in the tests below.
        return run_id, output_dir


def _patch_loss(
    monkeypatch,
    scripted_losses: list[float],
    *,
    seed_loss: float = 0.7,
) -> None:
    """Patch compute_run_loss. First value goes to the seed read; the rest
    are doled out to iterations in order."""
    losses = iter([seed_loss] + list(scripted_losses))
    from awp.refinement import loop as loop_mod

    def fake_compute(run_dir, *args, **kwargs):
        class B:
            total = next(losses)
            raw_signals = {}
        return B()

    monkeypatch.setattr(loop_mod, "compute_run_loss", fake_compute)


def test_loop_runs_until_max_iterations(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.5, 0.4, 0.3])

    workflow = StubWorkflow(losses=[0.5, 0.4, 0.3])
    loop = RefinementLoop(seed_run_dir=seed, workflow_factory=workflow,
                          iterations_root=tmp_path / "iters")
    result: RefinementResult = loop.run(iterations=3)

    assert result.stop_reason == "max_iterations"
    assert len(result.iterations) == 3
    assert result.best_iter == 3


def test_loop_stops_on_regression_after_two_worse_iterations(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    # iter 1 improves, iter 2 regresses, iter 3 regresses → stop.
    _patch_loss(monkeypatch, [0.3, 0.4, 0.5])

    workflow = StubWorkflow(losses=[0.3, 0.4, 0.5])
    loop = RefinementLoop(seed_run_dir=seed, workflow_factory=workflow,
                          iterations_root=tmp_path / "iters")
    result = loop.run(iterations=5)

    assert result.stop_reason == "regression"
    assert result.best_iter == 1
    assert len(result.iterations) == 3  # stopped after 3, did not run 4-5


def test_loop_stops_on_plateau(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    # 0.40 → 0.395 → 0.394 → deltas <0.01 twice in a row.
    _patch_loss(monkeypatch, [0.40, 0.395, 0.394])

    workflow = StubWorkflow(losses=[0.40, 0.395, 0.394])
    loop = RefinementLoop(seed_run_dir=seed, workflow_factory=workflow,
                          iterations_root=tmp_path / "iters")
    result = loop.run(iterations=5)
    assert result.stop_reason == "plateau"


def test_loop_aborts_on_empty_gradient(tmp_path: Path) -> None:
    seed = _make_seed(tmp_path, with_gradient=False)
    loop = RefinementLoop(seed_run_dir=seed, workflow_factory=lambda **_: None,
                          iterations_root=tmp_path / "iters")
    with pytest.raises(NothingToRefine):
        loop.run(iterations=2)


def test_loop_writes_gradient_input_and_r36_is_enforced(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.3])

    workflow = StubWorkflow(losses=[0.3])
    loop = RefinementLoop(seed_run_dir=seed, workflow_factory=workflow,
                          iterations_root=tmp_path / "iters")
    loop.run(iterations=1)

    # R36: gradient_input.json must have been persisted before iter 1 ran.
    iter1_dir = next((tmp_path / "iters").iterdir())
    assert (iter1_dir / "gradient_input.json").exists()
    content = json.loads((iter1_dir / "gradient_input.json").read_text(encoding="utf-8"))
    assert content["defects"], "gradient must carry defects"


def test_loop_parent_run_id_chain(monkeypatch, tmp_path: Path) -> None:
    seed = _make_seed(tmp_path)
    _patch_loss(monkeypatch, [0.4, 0.3])

    workflow = StubWorkflow(losses=[0.4, 0.3])
    loop = RefinementLoop(seed_run_dir=seed, workflow_factory=workflow,
                          iterations_root=tmp_path / "iters")
    result = loop.run(iterations=2)

    assert result.iterations[0].parent_run_id == "run_seed"
    assert result.iterations[1].parent_run_id == result.iterations[0].run_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest packages/awp-runtime/tests/refinement/test_loop.py -v`
Expected: FAIL with module import error.

- [ ] **Step 3: Implement `loop.py`**

Create `packages/awp-runtime/src/awp/refinement/loop.py`:

```python
"""RefinementLoop — orchestrator for iterative deliverable refinement.

The loop is a thin driver around ``AgentWorkflow``:

1. Read prior run → build ``RefinementGradient``.
2. Enforce R36 — non-empty gradient required.
3. Prepare workspace (hard-link prior ``FINAL/`` as ``input/``).
4. Persist ``gradient_input.json`` (R36 audit trail).
5. Invoke the workflow factory (default: wraps AgentWorkflow).
6. Compute loss via ``compute_run_loss``.
7. Apply stop-condition state machine.
8. Write session sidecar + BEST/ pointer.

The workflow factory is injected for testability — production uses
``default_workflow_factory`` which wraps AgentWorkflow.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from awp.outer_loop.loss import compute_run_loss
from awp.refinement.budget import budget_for_iteration
from awp.refinement.gradient import (
    RefinementGradient,
    extract_gradient,
    render_refinement_prefix,
)
from awp.refinement.seed import prepare_iteration_workspace
from awp.refinement.session import (
    RefinementIteration,
    RefinementSession,
    write_best_pointer,
    write_session_sidecar,
)

logger = logging.getLogger(__name__)

# (run_id, run_dir)
WorkflowFactory = Callable[..., tuple[str, Path]]


class NothingToRefine(RuntimeError):
    """R36: empty gradient — refinement aborted before iteration 1."""


@dataclass
class IterationOutcome:
    k: int
    run_id: str
    run_dir: Path
    loss: float
    status: str
    parent_run_id: str


@dataclass
class RefinementResult:
    session_id: str
    seed_run_id: str
    seed_loss: float
    best_iter: int  # 0 = seed wins
    best_loss: float
    stop_reason: str
    iterations: list[IterationOutcome] = field(default_factory=list)


_PLATEAU_EPS = 0.01
_PLATEAU_REQUIRED = 2
_REGRESSION_REQUIRED = 2
_WALL_TIME_FACTOR = 2.0


class RefinementLoop:
    """Stateful driver for a refinement session against a single seed run."""

    def __init__(
        self,
        *,
        seed_run_dir: Path,
        workflow_factory: WorkflowFactory | None = None,
        iterations_root: Path | None = None,
        model: str | None = None,
        worker_model: str | None = None,
    ) -> None:
        self._seed = seed_run_dir
        self._factory = workflow_factory or default_workflow_factory
        self._iterations_root = iterations_root or (
            Path("/tmp/awp-experiments") / f"refine_{int(time.time())}"
        )
        self._model = model
        self._worker_model = worker_model

    # ------------------------------------------------------------------

    def run(self, *, iterations: int) -> RefinementResult:
        iterations = max(1, min(10, int(iterations)))
        session_id = _new_session_id()
        started_at = _utcnow()

        # R36 — gradient must be non-empty before we even enter the loop.
        gradient = extract_gradient(self._seed)
        if not gradient.is_non_empty():
            raise NothingToRefine(
                f"seed {self._seed} has no defects, rejections, or eval gaps"
            )

        seed_budget, seed_wall_time, seed_task, seed_loss = self._read_seed_context()
        self._iterations_root.mkdir(parents=True, exist_ok=True)

        outcomes: list[IterationOutcome] = []
        last_loss: float | None = None
        regression_streak = 0
        plateau_streak = 0
        best_iter = 0
        best_loss = seed_loss
        cumulative_wall = 0.0
        wall_cap = seed_wall_time * _WALL_TIME_FACTOR
        parent_run_id = _safe_run_id(self._seed)
        stop_reason = "max_iterations"

        for k in range(1, iterations + 1):
            prior_final = (
                self._seed / "FINAL"
                if k == 1
                else outcomes[-1].run_dir / "FINAL"
            )

            workspace = self._iterations_root / f"iter_{k}"
            prepare_iteration_workspace(
                workspace_dir=workspace, prior_final_dir=prior_final
            )

            # Regenerate gradient from the prior iteration for k>1.
            current_gradient = (
                gradient if k == 1 else extract_gradient(outcomes[-1].run_dir)
            )
            # R36 re-check on each iteration — if an iteration somehow
            # produced a "perfect" run, stop here rather than burn budget.
            if not current_gradient.is_non_empty() and k > 1:
                stop_reason = "empty_gradient_midloop"
                break

            (workspace / "gradient_input.json").write_text(
                json.dumps(current_gradient.model_dump(), indent=2),
                encoding="utf-8",
            )

            prefix = render_refinement_prefix(current_gradient)

            iter_budget = budget_for_iteration(
                seed_budget=seed_budget, observed_wall_time=seed_wall_time
            )

            tags = ["refinement", f"refine-iter-{k}"]
            t0 = time.time()
            run_id, run_dir = self._factory(
                task=seed_task,
                inputs={"prior_deliverable_path": "input/"},
                initial_state={
                    "refinement_gradient": current_gradient.model_dump(),
                    "refinement_iteration": k,
                    "seed_run_id": _safe_run_id(self._seed),
                },
                output_dir=workspace,
                parent_run_id=parent_run_id,
                tags=tags,
                manager_prompt_prefix=prefix,
                budget=iter_budget,
                model=self._model,
                worker_model=self._worker_model,
            )
            cumulative_wall += time.time() - t0

            loss = float(compute_run_loss(run_dir).total)
            status = _read_status(run_dir)

            outcomes.append(
                IterationOutcome(
                    k=k,
                    run_id=run_id,
                    run_dir=run_dir,
                    loss=loss,
                    status=status,
                    parent_run_id=parent_run_id,
                )
            )

            if loss < best_loss:
                best_loss = loss
                best_iter = k

            if last_loss is None:
                regression_streak = 0
                plateau_streak = 0
            else:
                if loss >= last_loss:
                    regression_streak += 1
                else:
                    regression_streak = 0
                if abs(loss - last_loss) < _PLATEAU_EPS:
                    plateau_streak += 1
                else:
                    plateau_streak = 0

            last_loss = loss
            parent_run_id = run_id

            if regression_streak >= _REGRESSION_REQUIRED:
                stop_reason = "regression"
                break
            if plateau_streak >= _PLATEAU_REQUIRED:
                stop_reason = "plateau"
                break
            if cumulative_wall >= wall_cap and k < iterations:
                stop_reason = "wall_time_exhausted"
                break

        completed_at = _utcnow()
        session = RefinementSession(
            session_id=session_id,
            seed_run_id=_safe_run_id(self._seed),
            started_at=started_at,
            completed_at=completed_at,
            stop_reason=stop_reason,
            best_iter=best_iter,
            iterations=[
                RefinementIteration(k=o.k, run_id=o.run_id, loss=o.loss, status=o.status)
                for o in outcomes
            ],
        )
        write_session_sidecar(seed_run_dir=self._seed, session=session)

        if best_iter > 0:
            winning = outcomes[best_iter - 1].run_dir
            write_best_pointer(
                seed_run_dir=self._seed,
                winning_run_dir=winning,
                session_id=session_id,
                best_loss=best_loss,
                seed_loss=seed_loss,
            )

        return RefinementResult(
            session_id=session_id,
            seed_run_id=_safe_run_id(self._seed),
            seed_loss=seed_loss,
            best_iter=best_iter,
            best_loss=best_loss,
            stop_reason=stop_reason,
            iterations=outcomes,
        )

    # ------------------------------------------------------------------

    def _read_seed_context(self) -> tuple[dict[str, Any], float, str, float]:
        rc = json.loads((self._seed / "run_completion.json").read_text(encoding="utf-8"))
        budget_cfg = rc.get("budget") or {}
        observed_wall = float(budget_cfg.get("observed_wall_time") or rc.get("wall_time") or 0.0)
        seed_task = str(rc.get("task") or "")
        if not seed_task:
            raise ValueError(f"seed {self._seed} has no task recorded")

        budget = {
            "max_loops": int(budget_cfg.get("max_loops") or rc.get("max_loops") or 20),
            "max_total_workers": int(budget_cfg.get("max_total_workers") or 20),
            "max_total_tokens": int(budget_cfg.get("max_total_tokens") or 1_000_000),
            "max_wall_time": int(budget_cfg.get("max_wall_time") or 3600),
            "max_depth": int(budget_cfg.get("max_depth") or 4),
            "max_tool_calls": int(budget_cfg.get("max_tool_calls") or 600),
        }
        seed_loss = float(compute_run_loss(self._seed).total)
        return budget, observed_wall, seed_task, seed_loss


def default_workflow_factory(
    *,
    task: str,
    inputs: dict[str, Any],
    initial_state: dict[str, Any],
    output_dir: Path,
    parent_run_id: str,
    tags: list[str],
    manager_prompt_prefix: str,
    budget: dict[str, Any],
    model: str | None,
    worker_model: str | None,
) -> tuple[str, Path]:
    """Production factory — wraps AgentWorkflow."""
    # Lazy import to avoid dragging the runtime into import-time cycles.
    from awp.data.workflow import AgentWorkflow

    wf = AgentWorkflow(
        inputs=inputs or {},
        task=task,
        model=model or "openai/gpt-5-mini",
        worker_model=worker_model,
        output_dir=str(output_dir),
        parent_run_id=parent_run_id,
        tags=tags,
        manager_prompt_prefix=manager_prompt_prefix,
        max_loops=budget["max_loops"],
        max_total_workers=budget["max_total_workers"],
        max_total_tokens=budget["max_total_tokens"],
        max_wall_time=budget["max_wall_time"],
        max_tool_calls=budget["max_tool_calls"],
        max_depth=budget["max_depth"],
    )
    response = wf.run()
    meta = response.get("metadata", {}) if isinstance(response, dict) else {}
    run_id = str(meta.get("run_id") or uuid.uuid4())
    # AgentWorkflow writes run_completion.json somewhere under workspace;
    # locate it the same way the outer-loop runner does.
    workspace = Path(meta.get("workspace") or output_dir)
    for candidate in (workspace, *workspace.rglob("run_completion.json")):
        if isinstance(candidate, Path) and candidate.name == "run_completion.json":
            return run_id, candidate.parent
        if (candidate / "run_completion.json").exists():
            return run_id, candidate
    return run_id, workspace


def _new_session_id() -> str:
    return "refine_" + _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_run_id(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if rc.exists():
        try:
            return str(json.loads(rc.read_text(encoding="utf-8")).get("run_id") or run_dir.name)
        except json.JSONDecodeError:
            pass
    return run_dir.name


def _read_status(run_dir: Path) -> str:
    rc = run_dir / "run_completion.json"
    if not rc.exists():
        return "unknown"
    try:
        return str(json.loads(rc.read_text(encoding="utf-8")).get("status", "unknown"))
    except json.JSONDecodeError:
        return "unknown"
```

- [ ] **Step 4: Export and run tests**

Append to `packages/awp-runtime/src/awp/refinement/__init__.py`:

```python
from awp.refinement.loop import (
    IterationOutcome,
    NothingToRefine,
    RefinementLoop,
    RefinementResult,
)

__all__ = __all__ + [
    "IterationOutcome",
    "NothingToRefine",
    "RefinementLoop",
    "RefinementResult",
]
```

Run: `pytest packages/awp-runtime/tests/refinement/test_loop.py -v`
Expected: 6 tests PASS.

- [ ] **Step 5: Re-run the E2E — more assertions unblock**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py -v 2>&1 | tail -40`
Expected: `test_e2e_r36_aborts_on_empty_gradient` PASS. Others still SKIP waiting on Task 15 fixture.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-runtime/src/awp/refinement/loop.py \
        packages/awp-runtime/src/awp/refinement/__init__.py \
        packages/awp-runtime/tests/refinement/test_loop.py
git commit -m "$(cat <<'EOF'
feat(refinement): RefinementLoop orchestrator with stop conditions

Drives the refinement session: gradient extraction, R36 enforcement,
workspace prep, workflow factory invocation, loss accounting,
regression/plateau/wall-time stops, best-iter tracking, session
sidecar + BEST pointer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**E2E Progress:** 2 green assertions now (`test_e2e_budget_halved_per_iteration`, `test_e2e_r36_aborts_on_empty_gradient`).

---

## Task 8: CLI — `awp refine` subcommand

**Files:**
- Modify: `packages/awp-core/src/awp/cli.py`
- Create: `packages/awp-runtime/tests/refinement/test_cli.py`

- [ ] **Step 1: Inspect the existing CLI to match its style**

Run: `grep -n "^def\|@.*\.command\|@click\.command\|register" packages/awp-core/src/awp/cli.py | head -30`

This tells the implementer which CLI framework the file uses (click / argparse / typer). The `refine` command must follow the same style.

- [ ] **Step 2: Write the failing integration test**

Create `packages/awp-runtime/tests/refinement/test_cli.py`:

```python
"""Integration test: `awp refine` CLI wired to RefinementLoop."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _make_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "paper.md").write_text("# seed\n", encoding="utf-8")
    (seed / "run_completion.json").write_text(
        json.dumps({
            "run_id": "run_seed",
            "status": "partial",
            "confidence": 0.6,
            "task": "test task",
            "critique": {"defects": [{"summary": "bad", "severity": "high"}]},
            "evaluation": {"per_metric": {"m": 0.5}, "thresholds": {"m": 0.9}, "total_score": 0.5},
        }),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")
    return seed


def test_refine_cli_empty_gradient_exit_0(tmp_path: Path) -> None:
    seed = tmp_path / "perfect"
    (seed / "FINAL").mkdir(parents=True)
    (seed / "FINAL" / "a.md").write_text("ok", encoding="utf-8")
    (seed / "run_completion.json").write_text(
        json.dumps({
            "run_id": "run_perfect",
            "status": "complete",
            "confidence": 1.0,
            "task": "trivial",
            "critique": {"defects": []},
            "evaluation": {"per_metric": {"q": 1.0}, "thresholds": {"q": 0.5}, "total_score": 1.0},
        }),
        encoding="utf-8",
    )
    (seed / "events.jsonl").write_text("", encoding="utf-8")

    awp_bin = shutil.which("awp") or "awp"
    result = subprocess.run(
        [awp_bin, "refine", str(seed), "--iterations", "1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "nothing to refine" in (result.stdout + result.stderr).lower()


def test_refine_cli_missing_seed_exit_2(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "awp", "refine", str(tmp_path / "no_such"), "--iterations", "1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
```

- [ ] **Step 3: Run the test — expect failure**

Run: `pytest packages/awp-runtime/tests/refinement/test_cli.py -v`
Expected: FAIL — `awp refine` subcommand doesn't exist yet.

- [ ] **Step 4: Implement the CLI command**

Locate the CLI framework in `packages/awp-core/src/awp/cli.py`. Add a new subcommand that mirrors the style of existing commands (e.g. `awp run`).

Example using click (adjust to match the file's actual framework):

```python
@main.command("refine")
@click.argument("seed", type=click.Path(exists=False, file_okay=False, dir_okay=True))
@click.option("--iterations", "-n", type=int, default=3, show_default=True)
@click.option("--model", default=None)
@click.option("--worker-model", default=None)
def refine_cmd(seed: str, iterations: int, model: str | None, worker_model: str | None) -> None:
    """Iteratively refine a completed run's deliverable (task-local SGD on y)."""
    from pathlib import Path
    seed_path = Path(seed)
    if not seed_path.exists():
        click.echo(f"error: seed run not found: {seed_path}", err=True)
        raise SystemExit(2)
    if not (seed_path / "run_completion.json").exists():
        click.echo(f"error: seed has no run_completion.json: {seed_path}", err=True)
        raise SystemExit(2)
    if not (seed_path / "FINAL").exists():
        click.echo(f"error: seed has no FINAL/: {seed_path}", err=True)
        raise SystemExit(2)

    from awp.refinement.loop import NothingToRefine, RefinementLoop

    loop = RefinementLoop(
        seed_run_dir=seed_path,
        model=model,
        worker_model=worker_model,
    )
    try:
        result = loop.run(iterations=iterations)
    except NothingToRefine as exc:
        click.echo(f"nothing to refine: {exc}")
        raise SystemExit(0)

    click.echo(f"session_id: {result.session_id}")
    click.echo(f"stop_reason: {result.stop_reason}")
    click.echo(f"seed_loss: {result.seed_loss:.4f}")
    click.echo(f"best_loss: {result.best_loss:.4f} (iter {result.best_iter})")
    for it in result.iterations:
        click.echo(f"  iter {it.k}: run_id={it.run_id} loss={it.loss:.4f} status={it.status}")

    if result.best_iter == 0:
        raise SystemExit(1)
    raise SystemExit(0)
```

If the CLI uses a different framework, translate the structure accordingly. Behavior invariants: `--iterations` default 3, missing seed → exit 2, empty gradient → exit 0 with `"nothing to refine"` text, no improvement → exit 1.

- [ ] **Step 5: Run the CLI integration test**

Run: `pytest packages/awp-runtime/tests/refinement/test_cli.py -v`
Expected: 2 tests PASS.

- [ ] **Step 6: Smoke-test the CLI manually**

Run: `awp refine --help`
Expected: help text appears, mentions `--iterations`.

- [ ] **Step 7: Commit**

```bash
git add packages/awp-core/src/awp/cli.py packages/awp-runtime/tests/refinement/test_cli.py
git commit -m "feat(cli): add 'awp refine' subcommand

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** CLI layer exists. `test_e2e_cli_invocation_produces_session` is trivially green (it asserts nothing beyond the CLI test coverage).

---

## Task 9: R36 — spec insertion

**Files:**
- Modify: `spec/versions/1.0/validation-rules.md`

- [ ] **Step 1: Read the surrounding spec context**

Run: `awk '/^### R35/,/^### R3[6-9]|^## /' spec/versions/1.0/validation-rules.md` (or an equivalent tool) to confirm R35 is the last rule and where R36 should be inserted.

- [ ] **Step 2: Add R36 after R35**

Open `spec/versions/1.0/validation-rules.md` and append after the R35 block:

```markdown
### R36: Refinement Gradient Required

**Normative.** A refinement iteration SHALL have a non-empty
`gradient_input.json` present in its workspace directory before the
first manager call. The gradient is non-empty when at least one of the
following is true:

1. `defects` is a non-empty list,
2. `rejected_gates` is a non-empty list,
3. `eval_deltas` has at least one entry with a positive gap.

If the gradient is empty, the refinement loop SHALL abort with a
"nothing to refine" signal and SHALL NOT dispatch the iteration's
agent workflow.

**Rationale.** Prevents zero-signal reruns — a refinement call against
an already-perfect run wastes budget and confuses loss attribution.

**Enforcement.** Runtime: `awp.refinement.loop.RefinementLoop.run`
raises `NothingToRefine` before constructing `AgentWorkflow`.
`awp refine` CLI prints `"nothing to refine: <reason>"` and exits 0.
R36 is a runtime rule; `awp validate` does not evaluate it.
```

- [ ] **Step 3: Cross-reference in spec.md if needed**

Run: `grep -n "R35" spec/versions/1.0/spec.md`

If R35 is referenced there, add a similar parallel reference for R36. If not, no change needed.

- [ ] **Step 4: Run drift check**

Run: `python scripts/check_docs_drift.py`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add spec/versions/1.0/validation-rules.md spec/versions/1.0/spec.md
git commit -m "docs(spec): add R36 — refinement gradient required

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** Spec now codifies R36. E2E's `test_e2e_r36_aborts_on_empty_gradient` (already green) is formally backed by the normative rule.

---

## Task 10: `docs/refinement.md` — authoritative protocol doc

**Files:**
- Create: `docs/refinement.md`

- [ ] **Step 1: Write the doc**

Create `docs/refinement.md`. Copy the design spec structure but scope it to user-facing protocol:

```markdown
# AWP Refinement Mode

`awp refine` iteratively refines a completed run's deliverable using
critique defects, gate rejections, and eval deltas as the gradient.
It is orthogonal to `awp optimize` (which optimizes prompt artifacts
across a task suite) — refinement optimizes a single task's output
(y), not the policy (θ). The two commands do not share state and do
not interact in one invocation.

## When to use it

- A run completed with `status: partial` and a critique that flagged
  real defects.
- A run whose eval score is below threshold on one or more metrics.
- A run whose gate chain rejected COMPLETE attempts for reasons
  visible in `events.jsonl`.

## When NOT to use it

- The seed run completed with `status: complete` AND every eval metric
  above threshold AND zero critique defects. R36 aborts the call with
  exit 0 and message `"nothing to refine"`.
- You want to improve the *policy* for future runs — use
  `awp optimize` instead.

## CLI

    awp refine <seed_run_dir> [--iterations N] [--model M] [--worker-model M]

Exit codes:

| Code | Meaning |
|------|---------|
| `0`  | Improvement produced; `BEST/` updated. Also: empty gradient (nothing to do). |
| `1`  | No iteration improved loss. Seed still wins. |
| `2`  | Setup failure: seed missing / unreadable / no `FINAL/`. |

## Data flow

1. Read `<seed>/run_completion.json` + `<seed>/events.jsonl`.
2. Build `RefinementGradient` (defects, last 3 gate rejects, eval deltas).
3. R36 check — abort if gradient is empty.
4. For each iteration `k ∈ [1..N]`:
   1. Hard-link `<prior>/FINAL/` into `<workspace_k>/input/`.
   2. Persist `<workspace_k>/gradient_input.json`.
   3. Spawn `AgentWorkflow` with halved budget and the gradient prefix
      injected into iteration-1's manager user message.
   4. Compute loss via `compute_run_loss`.
   5. Apply stop-condition state machine.
5. Write `<seed>/refinement_sessions/<ts>.json` sidecar.
6. If improvement: update `<seed>/BEST/` (manifest + hard-linked files).

## Storage

- **Iteration run directory:** standalone experiment (usually under
  `/tmp/awp-experiments/refine_<ts>/iter_<k>/`) — an independent run
  with `parent_run_id` pointing at the prior iteration or the seed.
- **Session sidecar:** `<seed>/refinement_sessions/<session_id>.json`
  — records iteration list, best_iter, stop_reason.
- **BEST pointer:** `<seed>/BEST/` — hard-linked copy of the best
  iteration's `FINAL/` with `manifest.json` naming the winner. Only
  overwritten if a future session produces a lower loss than the
  incumbent.

## Stop conditions

| Condition | Trigger |
|-----------|---------|
| `max_iterations` | `k == N` |
| `regression` | `loss` rose vs. previous iter for 2 consecutive iterations |
| `plateau` | `|Δloss| < 0.01` for 2 consecutive iterations |
| `wall_time_exhausted` | cumulative wall-time ≥ 2 × seed observed wall-time |
| `empty_gradient` | R36 fires (only at iter 1) |
| `empty_gradient_midloop` | gradient went empty at iter k>1 (iteration ran succeeded completely) |

## Budget halving

Per iteration, counts (loops, workers, tool calls) are halved with
`ceil` and floored at 1; tokens are halved and floored at 1; wall-time
is halved from the seed's **observed** wall time and floored at 60 s;
depth is unchanged.

## R36 (normative)

A refinement iteration MUST have a non-empty `gradient_input.json`
before dispatch. See `spec/versions/1.0/validation-rules.md` for the
full rule text.

## Relationship to `awp optimize`

`awp optimize` is SGD over θ (prompt artifacts) with rollback on mean
loss regression. `awp refine` is test-time inference-compute scaling
over y (deliverable) with best-iter tracking. Neither imports the
other; running one does not affect the other's state.
```

- [ ] **Step 2: Run drift + sync checks**

Run: `python scripts/check_docs_drift.py && python scripts/check_sync_coverage.py`
Expected: exit 0 on both.

- [ ] **Step 3: Commit**

```bash
git add docs/refinement.md
git commit -m "docs(refinement): authoritative protocol doc for 'awp refine'

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** No direct E2E assertion, but `scripts/check_sync_coverage.py` now has a target doc to point at when refinement code changes.

---

## Task 11: Sync `CLAUDE.md`, `README.md`, `README_NERD.md`, `skill/SKILL.md`, `docs/e2e.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `README_NERD.md`
- Modify: `skill/SKILL.md`
- Modify: `docs/e2e.md`

- [ ] **Step 1: `CLAUDE.md` — Development Commands row**

Under `## Development Commands` in the CLI list, add:

```bash
awp refine <seed_run_dir>        # Iteratively refine a completed run's deliverable (task-local SGD on y)
```

- [ ] **Step 2: `CLAUDE.md` — Key Protocols bullet**

Under `### Key Protocols` add a new bullet:

```markdown
- **Refinement Mode (y-axis optimization)**: `awp refine <seed_run_dir>` wraps the existing delegation loop to iteratively refine a completed run's deliverable. Orthogonal to `awp optimize` (which moves θ — the prompt artifacts). Gradient = critique defects + last 3 gate rejections + eval deltas; injected as a deterministic prefix into iteration 1's manager user message only. Budget halved per iteration; stop on regression×2, plateau×2, wall-time cap (2× seed observed), or max iterations. R36 aborts on empty gradient. Iterations are independent experiments linked via `parent_run_id`; winning iteration hard-linked into `<seed>/BEST/`. Authoritative doc: `docs/refinement.md`.
```

- [ ] **Step 3: `CLAUDE.md` — sync-table row**

In the `§2 "Doc Sync as Definition-of-Done"` sync table, add:

```markdown
| Refinement mode code / behavior changed | `CLAUDE.md` (Key Protocols), `docs/refinement.md`, `spec/` (R36 if changed), `skill/SKILL.md` (refine command), `docs/e2e.md` (tag) |
```

- [ ] **Step 4: `README.md` — short mention**

In the section that lists the outer loop / optimization features, add one paragraph:

```markdown
### Refinement Mode

`awp refine <seed_run_dir>` iteratively refines a completed run's
deliverable using the prior run's critique + gate + eval signals as a
deterministic gradient. Orthogonal to `awp optimize` (which trains
prompt artifacts across a task suite); refinement applies extra
inference compute to a single task's output. See
[docs/refinement.md](docs/refinement.md).
```

- [ ] **Step 5: `README_NERD.md` — same, with θ/y framing**

```markdown
### Refinement Mode — y-axis optimization

`awp optimize` implements SGD over **θ** (the six prompt artifacts)
with rollback on mean-loss regression. `awp refine` is its sibling:
task-local SGD over **y** (the deliverable), driven by a deterministic
gradient extracted from the prior run's critique, gate rejections, and
eval deltas. The two are independent — refinement does not touch
prompts; optimize does not carry outputs forward. Together they form
the full optimization stack. Authoritative protocol:
[docs/refinement.md](docs/refinement.md).
```

- [ ] **Step 6: `skill/SKILL.md` — Commands reference**

Add to the commands reference section:

```markdown
### `awp refine <seed_run_dir>`

Iteratively refines a completed run's deliverable. Use when a seed run
ends at `partial` with critique defects or eval gaps. R36 aborts if
the seed is already "complete" with no measurable gap. Budget halved
per iteration; up to 10 iterations. Winning output hard-linked into
`<seed>/BEST/`. See `docs/refinement.md`.
```

- [ ] **Step 7: `docs/e2e.md` — add `refinement` tag**

In the tag list, add:

```markdown
- `refinement` — E2E covers `awp refine` behavior (gradient extraction, iteration chain, BEST pointer)
```

- [ ] **Step 8: Gate checks**

Run: `python scripts/check_docs_drift.py && python scripts/check_sync_coverage.py`
Expected: both exit 0.

- [ ] **Step 9: Commit**

```bash
git add CLAUDE.md README.md README_NERD.md skill/SKILL.md docs/e2e.md
git commit -m "docs: sync CLAUDE/README/SKILL/e2e for refinement mode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** No direct E2E assertion. Doc-sync gates are green.

---

## Task 12: Mirror `packages/` → `reference/python/src/`

**Why:** `scripts/check_mirror_drift.py` blocks commits when the published-package mirror diverges. The new refinement module and modified files must be copied.

**Files:**
- Create: `reference/python/src/awp/refinement/__init__.py`
- Create: `reference/python/src/awp/refinement/gradient.py`
- Create: `reference/python/src/awp/refinement/seed.py`
- Create: `reference/python/src/awp/refinement/budget.py`
- Create: `reference/python/src/awp/refinement/session.py`
- Create: `reference/python/src/awp/refinement/loop.py`
- Modify: `reference/python/src/awp/data/workflow.py`
- Modify: `reference/python/src/awp/runtime/delegation_loop_runner.py`
- Modify: `reference/python/src/awp/cli.py`

- [ ] **Step 1: Mirror the new package**

```bash
mkdir -p reference/python/src/awp/refinement
cp packages/awp-runtime/src/awp/refinement/*.py reference/python/src/awp/refinement/
```

- [ ] **Step 2: Mirror the modified files**

```bash
cp packages/awp-runtime/src/awp/data/workflow.py reference/python/src/awp/data/workflow.py
cp packages/awp-runtime/src/awp/runtime/delegation_loop_runner.py reference/python/src/awp/runtime/delegation_loop_runner.py
cp packages/awp-core/src/awp/cli.py reference/python/src/awp/cli.py
```

- [ ] **Step 3: Run the mirror drift check**

Run: `python scripts/check_mirror_drift.py`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add reference/python/src/awp/
git commit -m "chore(mirror): sync refinement module + touched files to reference/

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** Mirror gate green. `awp-agents` wheel builds from `reference/` will now include refinement mode.

---

## Task 13: Full local test sweep

**Files:** None (verification only).

- [ ] **Step 1: Run full unit + integration suite**

Run: `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" -x`
Expected: all PASS.

- [ ] **Step 2: Run drift + sync + mirror gates**

Run: `python scripts/check_docs_drift.py && python scripts/check_sync_coverage.py && python scripts/check_mirror_drift.py`
Expected: all exit 0.

- [ ] **Step 3: Ruff**

Run: `ruff check packages/ reference/ && ruff format --check packages/ reference/`
Expected: no issues. If issues: `ruff format packages/ reference/` and `ruff check --fix packages/ reference/`, then re-commit any fixes as a `chore: ruff` commit.

- [ ] **Step 4: If lint introduced changes, commit**

```bash
git add -A
git diff --cached --quiet || git commit -m "chore: ruff --fix on refinement mode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** All non-E2E green. Ready for the final real-LLM E2E step.

---

## Task 14: Wire the E2E seed-run fixture

**Why:** The E2E test file exists since Task 1 but its `seed_run_dir` fixture is stubbed with `pytest.skip`. This task fills it in with a real seed run so the remaining E2E assertions can actually execute.

**Files:**
- Modify: `packages/awp-runtime/tests/e2e/test_e2e_refinement.py`

- [ ] **Step 1: Replace the stub fixture with a real run**

In `test_e2e_refinement.py`, replace the `seed_run_dir` fixture:

```python
@pytest.fixture(scope="module")
def seed_run_dir() -> Path:
    """Real seed run (partial) against OpenRouter."""
    if not _has_llm_key():
        pytest.skip("real LLM required; no key configured")

    SEED_RUN_DIR.parent.mkdir(parents=True, exist_ok=True)
    if SEED_RUN_DIR.exists() and (SEED_RUN_DIR / "run_completion.json").exists():
        # Reuse the cached seed across test runs to avoid repeated LLM cost.
        return SEED_RUN_DIR

    if SEED_RUN_DIR.exists():
        shutil.rmtree(SEED_RUN_DIR)

    from awp.data.workflow import AgentWorkflow

    task = (
        "Write a 2-page bilingual (English + German) summary of the 1905 "
        "Einstein relativity paper. Include: (1) English abstract, "
        "(2) German abstract, (3) three labeled sections with citations."
    )
    # Intentionally tight budget so the run lands at 'partial' with a
    # detectable defect (missing citations / short German abstract).
    wf = AgentWorkflow(
        inputs={},
        task=task,
        model="openai/gpt-5-mini",
        worker_model="deepseek/deepseek-chat-v3.1",
        output_dir=str(SEED_RUN_DIR),
        max_loops=8,
        max_total_tokens=400_000,
        max_wall_time=600,
        max_total_workers=4,
        max_depth=2,
        tags=["e2e", "refinement", "seed"],
    )
    wf.run()
    assert (SEED_RUN_DIR / "run_completion.json").exists(), "seed run did not complete"
    assert (SEED_RUN_DIR / "FINAL").exists(), "seed run did not produce FINAL/"
    return SEED_RUN_DIR
```

- [ ] **Step 2: Fix the `_find_iteration_run_dir` helper**

Replace the helper stub with a real lookup:

```python
def _find_iteration_run_dir(run_id: str) -> Path:
    roots = [Path("/tmp/awp-experiments"), Path.home() / ".awp" / "experiments"]
    for root in roots:
        if not root.exists():
            continue
        for rc in root.rglob("run_completion.json"):
            try:
                data = json.loads(rc.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if data.get("run_id") == run_id:
                return rc.parent
    raise FileNotFoundError(f"no run dir for {run_id}")
```

- [ ] **Step 3: Commit (no LLM run yet)**

```bash
git add packages/awp-runtime/tests/e2e/test_e2e_refinement.py
git commit -m "test(e2e): wire real seed-run fixture for refinement E2E

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** Fixture is live. The next task runs it end-to-end.

---

## Task 15: Real-LLM E2E run — drive the full loop to green

**Why:** This is the terminal task. The E2E must pass against real LLMs before this plan can be declared done.

**Files:** None (execution only; code changes only if debug requires them).

- [ ] **Step 1: Verify the OpenRouter key**

Run: `bash -c 'source ~/.awp/.env 2>/dev/null; test -n "$OPENROUTER_API_KEY" && echo OK || echo MISSING'`
Expected: `OK`. If missing, obtain it from the location recorded in memory (`/home/shumway/projects/meta-agents/.env`).

- [ ] **Step 2: Actively monitor seed run**

Launch: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py::test_e2e_seed_run_has_expected_artifacts -v -s`

While running, tail `/tmp/awp-experiments/e2e-refinement/seed/events.jsonl` in another terminal. Per CLAUDE.md: **active monitoring is mandatory**. On stagnation (§3 HARD RULE), abort and diagnose before rerunning.

- [ ] **Step 3: Drive the remaining E2E assertions one at a time**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py -v -s 2>&1 | tee /tmp/e2e_refinement.log`

Expected-path check:
1. `test_e2e_seed_run_has_expected_artifacts` PASS (seed run real)
2. `test_e2e_gradient_is_non_empty` PASS
3. `test_e2e_refinement_prefix_includes_defects` PASS
4. `test_e2e_seed_workspace_prepared_for_iteration` PASS
5. `test_e2e_budget_halved_per_iteration` PASS (already green)
6. `test_e2e_iteration_has_parent_run_id_chain` PASS — requires an actual refinement session to have run
7. `test_e2e_best_pointer_and_session_sidecar_exist` PASS — same
8. `test_e2e_r36_aborts_on_empty_gradient` PASS (already green)
9. `test_e2e_cli_invocation_produces_session` PASS
10. `test_e2e_final_refinement_reduces_loss` PASS — **the terminal assertion**

To exercise tests 6/7/10 the E2E needs to actually **run** `awp refine` against the seed. Add a module-scoped fixture that invokes the CLI once before those tests:

```python
@pytest.fixture(scope="module")
def refinement_session(seed_run_dir: Path):
    """Run `awp refine` against the seed once and yield the session dict."""
    import shutil
    import subprocess

    awp_bin = shutil.which("awp") or "awp"
    result = subprocess.run(
        [awp_bin, "refine", str(seed_run_dir), "--iterations", "2"],
        capture_output=True,
        text=True,
        timeout=2400,
    )
    assert result.returncode in (0, 1), f"refine exited {result.returncode}: {result.stderr}"
    return _load_latest_session(seed_run_dir)
```

Then change tests 6/7/10 to take `refinement_session` as a fixture (or chain it implicitly via a dependent fixture — the simplest route is to add `refinement_session` to the signature of `test_e2e_iteration_has_parent_run_id_chain`, `test_e2e_best_pointer_and_session_sidecar_exist`, and `test_e2e_final_refinement_reduces_loss`).

Commit that adjustment as part of Step 14 if not already done.

- [ ] **Step 4: On failure, walk the 5-Why-by-Layer protocol on the LLM trace**

Per CLAUDE.md §3 — debugging E2E failures is pathology work, not symptom-string-matching. Open `/tmp/awp-experiments/e2e-refinement/seed/trace.jsonl` (or equivalent full trace) and the iteration run's trace, walk to layers 4–5, apply the production fix, rerun from scratch. No symptom patches, no retry loops to paper over flakes.

Stagnation (§E2E stagnation rule) = abort + fix + restart. Do not wait it out.

- [ ] **Step 5: Confirm all E2E tests green**

Run: `pytest packages/awp-runtime/tests/e2e/test_e2e_refinement.py -v`
Expected: every test PASS (none SKIP, none FAIL).

- [ ] **Step 6: Final regression pass**

Run: `pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -x`
Expected: everything PASS including the E2E file.

Run: `python scripts/check_docs_drift.py && python scripts/check_sync_coverage.py && python scripts/check_mirror_drift.py`
Expected: all exit 0.

- [ ] **Step 7: Commit any debug-induced fixes with proper attribution**

If Steps 3–4 required code changes, commit each fix with a `fix(...)` message that names the layer (per §3):

```bash
git commit -m "fix(refinement): <layer> — <root cause>

<story of what was symptom, what the real gradient in the system was,
 and why this edit is at the structural origin>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Summarize and hand off**

Post a final summary: all tests green, all doc-sync gates green, E2E demonstrates `loss(BEST) < loss(seed)`, list of commits since Task 0.

**E2E Progress:** **TERMINAL.** All 10 E2E assertions green against real LLMs. Plan complete.

---

---

## Added Tasks (scope update 2026-04-19)

---

## Task -1: Commit the design spec + plan as the first commit on main

**Why:** The subagent-driven workflow references these files. Committing them first gives every later commit a stable paper-trail origin. Per user directive: commit on `main`, do not push.

- [ ] **Step 1: Stage and commit the two docs**

```bash
cd /home/shumway/projects/agent-workflow-protocol
git add docs/superpowers/specs/2026-04-19-awp-refine-mode-design.md \
        docs/superpowers/plans/2026-04-19-awp-refine-mode.md
git commit -m "$(cat <<'EOF'
docs: add refinement-mode design spec + implementation plan

Design spec: task-local iterative refinement of a completed run's
deliverable, orthogonal to the outer-loop SGD over prompt artifacts.
Implementation plan: 16 tasks structured around an E2E test as the
north star, committed directly on main per user directive.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2: Verify commit landed**

Run: `git log --oneline -1`
Expected: the `docs: add refinement-mode design spec + implementation plan` commit.

**E2E Progress:** Paper trail established. No code moved.

---

## Task 16: UI backend — refinement endpoints

**Why:** User directive: refinement mode must be invokable from `awp-ui`, not just the CLI. The backend exposes one trigger endpoint and one read endpoint.

**Files:**
- Modify: `packages/awp-ui/server/api/routes.py`
- Modify: `packages/awp-ui/server/services/runner_service.py` (or the analogous service — discover via `grep -n "def run_" packages/awp-ui/server/services/`)
- Create: `packages/awp-ui/server/tests/test_refinement_routes.py`
- Mirror: `reference/python/src/server/api/routes.py` + any other server file touched

**Endpoint contracts:**

```
POST /api/experiments/{run_id}/refine
  body: {"iterations": int, "model": str | null, "worker_model": str | null}
  202 Accepted: {"session_id": "refine_<ts>", "status": "running"}
  404: seed run_id not found
  409: seed has no FINAL/ or status not in {"complete", "partial"}
  422: iterations out of [1, 10]

GET /api/experiments/{run_id}/refinement_sessions
  200: {"sessions": [<session JSON from refinement_sessions/*.json>...],
         "best": {...manifest.json...} | null}
  404: seed run_id not found
```

- [ ] **Step 1: Write the failing route tests**

Create `packages/awp-ui/server/tests/test_refinement_routes.py` using whatever test client style the existing `test_*_routes.py` files use (discover with `ls packages/awp-ui/server/tests/`). Assertions:

1. `POST /api/experiments/<run_id>/refine` with `iterations=2` returns `202` and a `session_id` starting with `"refine_"`.
2. Same POST with `iterations=11` returns `422`.
3. Same POST against a nonexistent `run_id` returns `404`.
4. `GET /api/experiments/<run_id>/refinement_sessions` returns `{"sessions": [...], "best": ...}`.

Use a fake seed-run dir fixture (see Task 7 test patterns) and monkey-patch `RefinementLoop.run` to avoid actually spawning agents.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest packages/awp-ui/server/tests/test_refinement_routes.py -v`
Expected: all four FAIL — the routes don't exist yet.

- [ ] **Step 3: Implement the routes**

In `packages/awp-ui/server/api/routes.py`, add two handlers following the file's existing framework (FastAPI likely — inspect existing routes to match style). The POST handler should:

1. Resolve `run_id` to a seed run directory (reuse whatever lookup the file already has for experiments).
2. Validate body schema + value ranges.
3. Instantiate `awp.refinement.loop.RefinementLoop(seed_run_dir=...)` and call `.run(iterations=...)` in a background task (use the existing background-task pattern — `BackgroundTasks` / `asyncio.create_task` / the `runner_service` pattern; pick whichever is idiomatic for the existing codebase).
4. Return `{"session_id": <generated>, "status": "running"}`.

The GET handler reads `<seed>/refinement_sessions/*.json` and `<seed>/BEST/manifest.json` (if present) and returns them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest packages/awp-ui/server/tests/test_refinement_routes.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Mirror + regression sweep + gates**

```bash
cp packages/awp-ui/server/api/routes.py reference/python/src/server/api/routes.py
# mirror any other touched server file similarly
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ packages/awp-ui/server/tests/ -k "not e2e" -x
python scripts/check_mirror_drift.py
```

All must be green.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-ui/server/ reference/python/src/server/
git commit -m "feat(ui-server): refinement endpoints (POST /refine, GET /refinement_sessions)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** Refinement is invokable from the UI backend. Frontend trigger in Task 17.

---

## Task 17: UI frontend — Refine button + modal + history panel

**Why:** Expose every user-tunable refinement setting through the UI. User directive: "mach auch alle einstellungen in der ui nutzbar" — all settings must be reachable from the UI, not just the CLI.

**Files:**
- Modify: the experiment detail component (discover with `grep -rln "ExperimentDetail\|experimentDetail" packages/awp-ui/frontend/src/` — likely `packages/awp-ui/frontend/src/components/Experiment/ExperimentDetail.tsx` or similar)
- Create: `packages/awp-ui/frontend/src/components/Refinement/RefineModal.tsx`
- Create: `packages/awp-ui/frontend/src/components/Refinement/RefinementHistory.tsx`
- Modify or create: `packages/awp-ui/frontend/src/api/refinement.ts` (follow the existing API-client pattern used by other files in `src/api/`)

**UI requirements — every setting must be editable in the UI:**

| Setting | UI control | Default | Constraints |
|---------|-----------|---------|-------------|
| `iterations` | number input | `3` | `[1, 10]` integer |
| `model` | **free-text `<input>`** (NOT `<select>`) | placeholder shows seed's model | any string |
| `worker_model` | **free-text `<input>`** (NOT `<select>`) | placeholder shows seed's worker model | any string |

CLAUDE.md explicitly forbids `<select>` dropdowns for model fields — free text only, provider is auto-detected backend-side.

**Behavior:**

- A "Refine" button on the experiment detail page, disabled unless the seed run's status is in `{"complete", "partial"}` and `FINAL/` exists.
- Click opens `RefineModal`. "Start refinement" submits to `POST /api/experiments/<run_id>/refine`, closes the modal, and kicks off polling.
- `RefinementHistory` renders below the detail block: table of all sessions for this seed (polled `GET /api/experiments/<run_id>/refinement_sessions` every 5 s while any session has no `completed_at`; stop polling once all are terminal).
- Per session row: `session_id`, `started_at`, `stop_reason`, `best_iter`, per-iteration mini-table (k, run_id, loss, status).
- If `BEST/manifest.json` exists, render a badge at the top of the detail page: `"BEST loss: <best_loss> (vs seed <seed_loss>, Δ -<delta>)"`.

- [ ] **Step 1: Discover the frontend toolchain**

Run: `cat packages/awp-ui/frontend/package.json | grep -E '"(test|vitest|jest|react)"' ; ls packages/awp-ui/frontend/src/components/`

Identify: test runner (vitest / jest), existing API-client style, existing modal/panel patterns. Match them exactly — no new conventions.

- [ ] **Step 2: Write the failing smoke test for RefineModal**

Create the smoke test in the project's existing frontend-test directory (e.g. `packages/awp-ui/frontend/src/components/Refinement/__tests__/RefineModal.test.tsx` or wherever co-located with existing component tests). Assertions:

1. Modal renders with `iterations` input pre-filled to 3.
2. Submitting calls `startRefinement(runId, {iterations, model, worker_model})` with the right payload.
3. `iterations > 10` disables the submit button or shows a validation error.

- [ ] **Step 3: Run test to verify it fails**

Run: from `packages/awp-ui/frontend/`: `npm test -- RefineModal` (or the equivalent for the project's test runner)
Expected: FAIL — component doesn't exist.

- [ ] **Step 4: Implement `RefineModal.tsx`**

Create it with iteration/model/worker_model inputs, validation, and a submit handler calling the API client. Match the visual/style pattern of any existing modal in `packages/awp-ui/frontend/src/components/`.

- [ ] **Step 5: Implement `RefinementHistory.tsx` + API client + detail integration**

Create the history panel (polling, rendering sessions). Add/extend `src/api/refinement.ts` with `startRefinement` and `getRefinementSessions` functions following the existing fetch-wrapper style. Integrate both into the experiment detail component: "Refine" button (Task 17 core) + history panel rendering below + BEST badge at the top.

- [ ] **Step 6: Frontend tests + regression**

Run: from `packages/awp-ui/frontend/`: `npm test -- Refine`
Expected: PASS. Then run the full frontend suite: `npm test -- --run` (vitest) or `npm test -- --watchAll=false` (jest). Expected: no regressions.

- [ ] **Step 7: Smoke-test in-browser**

```bash
# in one terminal
cd packages/awp-ui/server && uvicorn server.main:app --reload &
# in another
cd packages/awp-ui/frontend && npm run dev
```

Open the dev URL, pick an existing completed experiment, verify:
- "Refine" button appears and is enabled.
- Modal opens, inputs accept values, submit disabled at iterations=11, enabled at 1..10.
- Starting refinement shows the session in the history panel (initially `running`, then terminal).

Kill both dev servers after verification (per CLAUDE.md: always kill dev servers before starting new ones).

- [ ] **Step 8: Commit**

```bash
git add packages/awp-ui/frontend/
git commit -m "$(cat <<'EOF'
feat(ui-frontend): Refine button + modal + history + BEST badge

All refinement settings are reachable from the UI: iterations (1-10),
manager model (free text), worker model (free text). History panel
polls /refinement_sessions while any session is non-terminal. BEST
manifest renders as a badge when present.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Note on frontend mirror:** the frontend is a build artifact. `npm run build` + copy of `dist/` to `reference/python/src/server/frontend/dist/` is part of the PyPI release workflow — explicitly out of scope for this plan. `scripts/check_mirror_drift.py` does not cover the frontend dist, so the commit is safe.

**E2E Progress:** Refinement mode is reachable end-to-end from the UI — every user-tunable setting is exposed.

---

## Task 18: README "Key Features" section + docs/refinement.md link

**Why:** User directive — describe refinement mode as an MD file (already done in Task 10: `docs/refinement.md`) and link it in `README.md` under "Key Features".

- [ ] **Step 1: Check whether `README.md` already has a Key Features section**

Run: `grep -n "^##\s*Key Features\|^#\s*Key Features" README.md`

- [ ] **Step 2a: If the section exists, add the bullet**

Insert near the end of the existing Key Features list:

```markdown
- **Refinement Mode** — `awp refine <seed_run_dir>` iteratively refines a completed run's deliverable using critique, gate, and eval signals as a deterministic gradient. Orthogonal to `awp optimize` (prompt-artifact SGD). See [docs/refinement.md](docs/refinement.md).
```

- [ ] **Step 2b: If the section does not exist, create it**

Insert a new `## Key Features` section near the top of the README (after the hero/intro, before installation). Populate it with at least the Refinement-Mode bullet above. If other features are obviously worth listing (outer loop, delegation loop, tool induction), include them — but do not reorganize unrelated sections of the README.

- [ ] **Step 3: Drift + sync check**

Run: `python scripts/check_docs_drift.py && python scripts/check_sync_coverage.py`
Expected: exit 0 on both.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(readme): add Key Features section linking refinement mode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**E2E Progress:** README now surfaces refinement mode as a first-class feature linked to its protocol doc.

---

## Self-Review Checklist (run before marking plan done)

- [ ] Every spec section in `docs/superpowers/specs/2026-04-19-awp-refine-mode-design.md` maps to at least one task.
- [ ] No "TBD", "TODO", "add appropriate error handling" anywhere above.
- [ ] Type names are consistent — `RefinementGradient`, `RefinementLoop`, `NothingToRefine`, `RefinementSession`, `RefinementIteration`, `IterationOutcome`, `RefinementResult` used identically everywhere.
- [ ] Function signatures in later tasks match their definitions in earlier tasks:
  - `extract_gradient(prior_run_dir: Path) -> RefinementGradient` (Task 2)
  - `render_refinement_prefix(gradient: RefinementGradient) -> str` (Task 2)
  - `prepare_iteration_workspace(*, workspace_dir, prior_final_dir) -> Path` (Task 3)
  - `budget_for_iteration(*, seed_budget, observed_wall_time) -> dict` (Task 4)
  - `write_session_sidecar(*, seed_run_dir, session) -> Path` (Task 6)
  - `write_best_pointer(*, seed_run_dir, winning_run_dir, session_id, best_loss, seed_loss)` (Task 6)
  - `RefinementLoop(seed_run_dir, workflow_factory, iterations_root, model, worker_model).run(iterations) -> RefinementResult` (Task 7)
- [ ] Every task has an **E2E Progress** line stating which E2E assertion or gate it advances.
- [ ] Commit discipline: each task ends in exactly one commit (Task 13 may add a chore lint commit; Task 15 may add fix commits on failure).
- [ ] No PyPI release in scope — explicitly deferred.
