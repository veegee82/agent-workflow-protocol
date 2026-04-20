# Plan 3 — Continuation Loader: `awp run --target` for continuation tasks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `awp run --target <exp>:<continuation-task>` loads the prior task's `BEST/` bundle, composes a deterministic continuation prefix (primary material inline + reference path registry + user feedback as gradient), and passes it to `AgentWorkflow` as `manager_prompt_prefix`. The continuation task's seed-run Manager sees the prior deliverable in iteration 1 and builds on it — no re-derivation of prior work.

**Architecture:** Pure function-level module `awp.continuation` inside `awp-runtime`. Two files: `bundle_loader.py` (reads `task.json.inputs`, resolves source paths, builds a `ContinuationBundle`) + `prompt_injection.py` (turns the bundle + `user_feedback` into a deterministic prefix string, with context-budget fallbacks). The CLI dispatcher (`run_task_aware` in `cli_handlers.py`) calls into this module when the target task has `mode == "continuation"`; the Plan-2-Task-1 guard is lifted. Integration point is the existing `AgentWorkflow(... manager_prompt_prefix=...)` parameter — no runtime-internal changes.

**Tech Stack:** Python 3.10+, Pydantic v2, pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md` §7.1–§7.4, §11 (R37).

**Lessons from Plans 1 + 2 baked in here:**
- **No namespace-package collisions.** `awp.continuation` does not exist in `awp-core`. Safe to place module in `packages/awp-runtime/src/awp/continuation/`.
- **Flat test layout.** `packages/awp-runtime/tests/test_continuation_*.py` (NOT `tests/continuation/` with `__init__.py`) to avoid the collection collision that bit Plan 2 Task 3.
- **Real schemas in fixtures.** Any fake `run_completion.json` used in tests must use `{"eval": {"score": N}}` not `{"evaluation": ...}`.
- **Smoke-test gate.** Plan 3's final task is an end-to-end shell smoke test (no LLM), not just unit tests — catches the "fixture matches production" class of bug we hit in Plan 2.
- **Flag naming collision-check.** No new CLI flags are added in Plan 3 (only behaviour changes for existing `--target` when mode=continuation).

**Out of scope:**
- Real-LLM E2E of continuation (`tests/e2e/test_e2e_continuation.py`) — that belongs to the `e2e` tag group and will be written as a separate commit after Plan 3 lands, using a real OpenRouter key.
- Automatic bundle summarisation for very long chains (C-adjacent). Plan 3 uses metadata stubs for overflow; summarisation is a later refinement.
- Refine/Optimize relocation under `<task>/refinements/` and `<task>/optimizations/` (Plan 4).
- UI rendering of the continuation provenance (Plan 5).

---

## File structure

**Created:**
- `packages/awp-runtime/src/awp/continuation/__init__.py` — package marker. Exports `load_continuation_bundle` + `render_continuation_prefix` + `ContinuationBundle` + `ContinuationBudgetError`.
- `packages/awp-runtime/src/awp/continuation/bundle_loader.py` — `load_continuation_bundle`.
- `packages/awp-runtime/src/awp/continuation/prompt_injection.py` — `render_continuation_prefix`.
- `packages/awp-runtime/tests/test_continuation_bundle_loader.py` — flat test, no `__init__.py`.
- `packages/awp-runtime/tests/test_continuation_prompt_injection.py` — flat test, no `__init__.py`.
- `packages/awp-core/tests/cli/test_run_continuation_cli.py` — CLI-level integration (dry-run + mocked AgentWorkflow).
- `docs/continuation.md` — mechanism doc (next to `docs/refinement.md`).

**Modified:**
- `packages/awp-core/src/awp/experiment/cli_handlers.py` — lift the continuation gate in `validate_task_key_for_run`; extend `run_task_aware` to call the loader + pass `manager_prompt_prefix`.
- `CLAUDE.md` — document the continuation-run path in the Development Commands block.
- `spec/versions/1.0/validation-rules.md` — strengthen R37 with a runtime-enforcement note (the rule was already added in Plan 1 Task 12; Plan 3 adds a one-line runtime-enforcement reference).
- `reference/python/src/…` — mirror sync (final task).

---

## Known precondition: `AgentWorkflow` accepts `manager_prompt_prefix`

Verified during Plan 2 exploration (`packages/awp-runtime/src/awp/data/workflow.py:118-169`). The parameter is already plumbed through to `DelegationLoopRunner`, which (per the refinement spec) prepends it to the Manager's user message on iteration 1 of the seed run. If this ever regresses, Plan 3 is impossible; verify early in Task 4.

---

## Task 1: Bundle loader — reads `task.json.inputs`, resolves source paths

**Files:**
- Create: `packages/awp-runtime/src/awp/continuation/__init__.py`
- Create: `packages/awp-runtime/src/awp/continuation/bundle_loader.py`
- Test:   `packages/awp-runtime/tests/test_continuation_bundle_loader.py`

**Background.** A continuation task has `task.json` with a non-empty `inputs[]`. Each entry points at a `from_task` in the same experiment, with `role ∈ {primary, reference}` and exactly one of `bundle: "BEST/"` (shorthand for whole BEST dir) or `paths: [...]` (explicit relative paths). The loader enumerates concrete files for each entry.

- [ ] **Step 1: Write the failing test**

Create `packages/awp-runtime/tests/test_continuation_bundle_loader.py`:

```python
"""Tests for the continuation bundle loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awp.continuation.bundle_loader import (
    ContinuationBundle,
    ContinuationInputError,
    load_continuation_bundle,
)


def _mk_task_dir(exp_root: Path, exp_id: str, task_id: str) -> Path:
    td = exp_root / exp_id / "tasks" / task_id
    td.mkdir(parents=True, exist_ok=True)
    return td


def _mk_best(task_dir: Path, files: dict[str, str]) -> None:
    best = task_dir / "BEST"
    best.mkdir(parents=True, exist_ok=True)
    (best / "manifest.json").write_text('{"winner_run_id":"dummy"}')
    for relpath, content in files.items():
        p = best / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _write_task_json(task_dir: Path, content: dict) -> None:
    (task_dir / "task.json").write_text(json.dumps(content))


def test_single_primary_bundle_entry(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    parent = _mk_task_dir(tmp_path, exp, "001-seed")
    _mk_best(parent, {"paper.md": "draft v1", "analysis/facts.json": '{"x": 1}'})
    cont = _mk_task_dir(tmp_path, exp, "002-improve")
    _write_task_json(cont, {
        "task_id": "002-improve",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "deeper section 2",
        "inputs": [
            {"from_task": "001-seed", "role": "primary", "bundle": "BEST/"}
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })

    bundle = load_continuation_bundle(
        task_dir=cont, experiment_dir=tmp_path / exp
    )

    assert isinstance(bundle, ContinuationBundle)
    assert len(bundle.primary_materials) == 2
    relpaths = sorted(e.relative_path for e in bundle.primary_materials)
    assert relpaths == ["analysis/facts.json", "paper.md"]
    contents = {e.relative_path: e.content_text for e in bundle.primary_materials}
    assert contents["paper.md"] == "draft v1"
    assert bundle.reference_paths == []
    assert bundle.user_feedback == "deeper section 2"


def test_reference_explicit_paths(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    parent = _mk_task_dir(tmp_path, exp, "001-seed")
    _mk_best(parent, {"paper.md": "short", "analysis/facts.json": '{"x":1}'})
    cont = _mk_task_dir(tmp_path, exp, "002-x")
    _write_task_json(cont, {
        "task_id": "002-x",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "fb",
        "inputs": [
            {"from_task": "001-seed", "role": "primary", "bundle": "BEST/"},
            {"from_task": "001-seed", "role": "reference",
             "paths": ["BEST/analysis/facts.json"]},
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })

    bundle = load_continuation_bundle(
        task_dir=cont, experiment_dir=tmp_path / exp
    )

    # Primary still covers BEST/ contents
    assert len(bundle.primary_materials) == 2
    # Reference pointer recorded separately
    assert len(bundle.reference_paths) == 1
    assert bundle.reference_paths[0].source_task == "001-seed"
    assert bundle.reference_paths[0].relative_path == "BEST/analysis/facts.json"
    assert bundle.reference_paths[0].size_bytes > 0


def test_multi_task_inputs_delta(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    a = _mk_task_dir(tmp_path, exp, "001-a")
    _mk_best(a, {"draft.md": "A draft"})
    b = _mk_task_dir(tmp_path, exp, "002-b")
    _mk_best(b, {"bench.json": '{"score":0.9}'})
    cont = _mk_task_dir(tmp_path, exp, "003-c")
    _write_task_json(cont, {
        "task_id": "003-c",
        "experiment_id": exp,
        "task_number": 3,
        "mode": "continuation",
        "user_feedback": "combine",
        "inputs": [
            {"from_task": "001-a", "role": "primary", "bundle": "BEST/"},
            {"from_task": "002-b", "role": "reference",
             "paths": ["BEST/bench.json"]},
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })

    bundle = load_continuation_bundle(
        task_dir=cont, experiment_dir=tmp_path / exp
    )

    assert any(e.source_task == "001-a" for e in bundle.primary_materials)
    assert bundle.reference_paths[0].source_task == "002-b"


def test_missing_from_task_rejected(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    cont = _mk_task_dir(tmp_path, exp, "002-x")
    _write_task_json(cont, {
        "task_id": "002-x",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "fb",
        "inputs": [
            {"from_task": "001-missing", "role": "primary", "bundle": "BEST/"}
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    with pytest.raises(ContinuationInputError, match="not found"):
        load_continuation_bundle(task_dir=cont, experiment_dir=tmp_path / exp)


def test_from_task_without_best_rejected(tmp_path: Path) -> None:
    exp = "exp_aaaaaaaa"
    parent = _mk_task_dir(tmp_path, exp, "001-seed")
    # No BEST/ — task never completed
    cont = _mk_task_dir(tmp_path, exp, "002-x")
    _write_task_json(cont, {
        "task_id": "002-x",
        "experiment_id": exp,
        "task_number": 2,
        "mode": "continuation",
        "user_feedback": "fb",
        "inputs": [
            {"from_task": "001-seed", "role": "primary", "bundle": "BEST/"}
        ],
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    with pytest.raises(ContinuationInputError, match="BEST"):
        load_continuation_bundle(task_dir=cont, experiment_dir=tmp_path / exp)


def test_seed_task_raises(tmp_path: Path) -> None:
    """Loader is only valid for continuation tasks."""
    exp = "exp_aaaaaaaa"
    cont = _mk_task_dir(tmp_path, exp, "001-s")
    _write_task_json(cont, {
        "task_id": "001-s",
        "experiment_id": exp,
        "task_number": 1,
        "mode": "seed",
        "user_prompt": "p",
        "inputs": [],
        "created_at": "2026-04-20T00:00:00+00:00",
    })
    with pytest.raises(ContinuationInputError, match="not a continuation"):
        load_continuation_bundle(task_dir=cont, experiment_dir=tmp_path / exp)
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

```
pytest packages/awp-runtime/tests/test_continuation_bundle_loader.py -v
```

- [ ] **Step 3: Implement the loader**

Create `packages/awp-runtime/src/awp/continuation/__init__.py`:

```python
"""Continuation loader — y-axis carry-over across tasks.

Reads a continuation task's `task.json.inputs`, resolves each `from_task`
to its prior BEST bundle, and produces a deterministic prefix for the
Manager prompt.
"""

from .bundle_loader import (
    BundleEntry,
    ContinuationBundle,
    ContinuationInputError,
    ReferencePointer,
    load_continuation_bundle,
)
from .prompt_injection import (
    ContinuationBudgetError,
    render_continuation_prefix,
)

__all__ = [
    "BundleEntry",
    "ContinuationBundle",
    "ContinuationBudgetError",
    "ContinuationInputError",
    "ReferencePointer",
    "load_continuation_bundle",
    "render_continuation_prefix",
]
```

Create `packages/awp-runtime/src/awp/continuation/bundle_loader.py`:

```python
"""Continuation bundle loader."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


class ContinuationInputError(Exception):
    """Raised when a continuation input cannot be resolved on disk."""


@dataclass
class BundleEntry:
    """One primary file loaded into memory."""
    source_task: str
    relative_path: str           # relative to the source task dir
    content_text: str            # UTF-8 decoded content


@dataclass
class ReferencePointer:
    """One reference path — Manager may fetch via fs.read if needed."""
    source_task: str
    relative_path: str
    size_bytes: int
    summary_head: str            # first 200 chars


@dataclass
class ContinuationBundle:
    primary_materials: list[BundleEntry] = field(default_factory=list)
    reference_paths: list[ReferencePointer] = field(default_factory=list)
    user_feedback: str = ""


def load_continuation_bundle(
    task_dir: Path, experiment_dir: Path
) -> ContinuationBundle:
    """Read `task.json`, resolve inputs, build a ContinuationBundle.

    Raises ContinuationInputError on: wrong mode, missing from_task,
    from_task without BEST, explicit path outside source task dir.
    """
    task_json = task_dir / "task.json"
    if not task_json.exists():
        raise ContinuationInputError(f"task.json not found at {task_json}")
    task = json.loads(task_json.read_text(encoding="utf-8"))
    if task.get("mode") != "continuation":
        raise ContinuationInputError(
            f"task {task.get('task_id')} is not a continuation"
        )
    bundle = ContinuationBundle(user_feedback=task.get("user_feedback", ""))

    for entry in task.get("inputs", []):
        src_task_id = entry["from_task"]
        role = entry["role"]
        src_dir = experiment_dir / "tasks" / src_task_id
        if not src_dir.exists():
            raise ContinuationInputError(
                f"from_task not found: {src_task_id}"
            )
        src_best = src_dir / "BEST"
        if not src_best.exists():
            raise ContinuationInputError(
                f"from_task {src_task_id} has no BEST/ — run it to completion first"
            )

        # Resolve paths: either whole BEST/ (bundle shorthand) or explicit paths
        if entry.get("bundle"):
            # Enumerate files under BEST/, excluding manifest.json
            file_list = [
                p for p in src_best.rglob("*")
                if p.is_file() and p.name != "manifest.json"
            ]
            rel_paths = [str(p.relative_to(src_dir)) for p in file_list]
        else:
            rel_paths = list(entry.get("paths", []))

        for rel in rel_paths:
            # Safety: reject traversal
            if ".." in rel.split("/") or rel.startswith("/"):
                raise ContinuationInputError(
                    f"path escapes source task: {rel!r}"
                )
            abs_path = src_dir / rel
            if not abs_path.exists() or not abs_path.is_file():
                raise ContinuationInputError(
                    f"referenced file not found: {src_task_id}/{rel}"
                )
            if role == "primary":
                bundle.primary_materials.append(
                    BundleEntry(
                        source_task=src_task_id,
                        relative_path=rel[len("BEST/"):] if rel.startswith("BEST/") else rel,
                        content_text=abs_path.read_text(encoding="utf-8"),
                    )
                )
            elif role == "reference":
                head = ""
                try:
                    head = abs_path.read_text(encoding="utf-8")[:200]
                except UnicodeDecodeError:
                    head = "<binary>"
                bundle.reference_paths.append(
                    ReferencePointer(
                        source_task=src_task_id,
                        relative_path=rel,
                        size_bytes=abs_path.stat().st_size,
                        summary_head=head,
                    )
                )
            else:
                raise ContinuationInputError(
                    f"unknown role {role!r} for input from {src_task_id}"
                )

    return bundle
```

Also create `packages/awp-runtime/src/awp/continuation/prompt_injection.py` as a minimal stub (implemented in Task 2):

```python
"""Continuation prefix rendering — filled in Task 2."""

from __future__ import annotations


class ContinuationBudgetError(Exception):
    """Raised when even the primary material alone exceeds the budget."""


def render_continuation_prefix(*_args, **_kwargs) -> str:
    raise NotImplementedError("implemented in Plan 3 Task 2")
```

- [ ] **Step 4: Verify**

```
pytest packages/awp-runtime/tests/test_continuation_bundle_loader.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Full regression**

```
pytest packages/awp-runtime/tests/ -k "not e2e" 2>&1 | tail -5
```

Expected: green (plus 1 pre-existing `test_manager_prompt_uses_default_worker_pitfalls`).

- [ ] **Step 6: Commit**

```bash
git add packages/awp-runtime/src/awp/continuation/ packages/awp-runtime/tests/test_continuation_bundle_loader.py
git commit -m "feat(runtime): continuation bundle loader (reads task.json.inputs)"
```

---

## Task 2: Prompt injection — `render_continuation_prefix`

**Files:**
- Modify: `packages/awp-runtime/src/awp/continuation/prompt_injection.py`
- Test:   `packages/awp-runtime/tests/test_continuation_prompt_injection.py`

**Background.** Given a `ContinuationBundle`, produce a deterministic text block that goes into the Manager's iteration-1 user message. Semantics:

1. `## Continuation Context` header.
2. `### Prior deliverable (primary)` section — each primary entry inlined with its source-task + relative-path as a sub-heading.
3. `### Reference material (available via fs.read)` — one line per reference entry: source_task, relative path, size, first 200 chars.
4. `## User Feedback` — the `user_feedback` string verbatim.
5. `## Your Task` — fixed boilerplate instructing the Manager to build on the prior material and use references only when the feedback requires it.

Budget guard (default: 120_000 tokens ≈ 480_000 chars, matches 0.8 × `manager_context_budget_tokens`):
- If total fits → return as-is.
- Otherwise compress reference section to metadata-only stubs (path + size, no first-200-chars).
- If still over → drop references entirely.
- If primary alone exceeds budget → raise `ContinuationBudgetError` with a message suggesting to split.

- [ ] **Step 1: Write failing tests**

Create `packages/awp-runtime/tests/test_continuation_prompt_injection.py`:

```python
"""Tests for continuation prefix rendering."""

from __future__ import annotations

import pytest

from awp.continuation import (
    BundleEntry,
    ContinuationBudgetError,
    ContinuationBundle,
    ReferencePointer,
    render_continuation_prefix,
)


def _bundle(primaries, references=None, feedback="test"):
    return ContinuationBundle(
        primary_materials=list(primaries),
        reference_paths=list(references or []),
        user_feedback=feedback,
    )


def test_prefix_contains_sections() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-seed", "paper.md", "This is the paper body.")],
        feedback="make section 3 deeper",
    )
    prefix = render_continuation_prefix(b)
    assert "## Continuation Context" in prefix
    assert "### Prior deliverable (primary)" in prefix
    assert "paper.md" in prefix
    assert "This is the paper body." in prefix
    assert "## User Feedback" in prefix
    assert "make section 3 deeper" in prefix
    assert "## Your Task" in prefix


def test_reference_section_present_when_given() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "A")],
        references=[ReferencePointer("001-s", "BEST/b.json", 1234, '{"x": 1}')],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b)
    assert "### Reference material" in prefix
    assert "BEST/b.json" in prefix
    assert "1234" in prefix
    assert '{"x": 1}' in prefix


def test_reference_section_omitted_when_empty() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "A")],
        references=[],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b)
    assert "### Reference material" not in prefix


def test_determinism() -> None:
    b = _bundle(
        primaries=[
            BundleEntry("001-s", "a.md", "A"),
            BundleEntry("001-s", "b.md", "B"),
        ],
        feedback="fb",
    )
    assert render_continuation_prefix(b) == render_continuation_prefix(b)


def test_reference_stub_degradation() -> None:
    # Build a tiny primary + a huge reference-head
    big_head = "x" * 400_000
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "A")],
        references=[ReferencePointer("001-s", "big.json", 1_000_000, big_head)],
        feedback="fb",
    )
    # With a tight budget the first-200-chars must drop
    prefix = render_continuation_prefix(b, max_chars=5_000)
    assert big_head[:100] not in prefix  # head was stripped
    assert "big.json" in prefix          # path still listed
    assert "1000000" in prefix           # size still listed


def test_reference_drop_when_still_over() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "a.md", "tiny")],
        references=[
            ReferencePointer("001-s", f"f{i}.md", 100, "head" * 50)
            for i in range(200)
        ],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b, max_chars=1_000)
    assert "### Reference material" not in prefix
    assert "tiny" in prefix  # primary preserved


def test_primary_overflow_raises() -> None:
    b = _bundle(
        primaries=[BundleEntry("001-s", "big.md", "y" * 100_000)],
        feedback="fb",
    )
    with pytest.raises(ContinuationBudgetError, match="primary"):
        render_continuation_prefix(b, max_chars=1_000)


def test_max_chars_default_honors_80pct_of_150k_tokens() -> None:
    # Default budget ≈ 480_000 chars (0.8 × 150_000 tokens × 4 chars/token).
    # A 300_000-char primary should fit without error.
    b = _bundle(
        primaries=[BundleEntry("001-s", "big.md", "y" * 300_000)],
        feedback="fb",
    )
    prefix = render_continuation_prefix(b)
    assert "y" * 100 in prefix
```

- [ ] **Step 2: Run — expect NotImplementedError (Task 1 left a stub)**

```
pytest packages/awp-runtime/tests/test_continuation_prompt_injection.py -v
```

- [ ] **Step 3: Implement `render_continuation_prefix`**

Replace the stub in `packages/awp-runtime/src/awp/continuation/prompt_injection.py`:

```python
"""Deterministic continuation prefix rendering.

See Plan 3 design in docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md §7.2–7.3.
"""

from __future__ import annotations

from .bundle_loader import BundleEntry, ContinuationBundle, ReferencePointer


class ContinuationBudgetError(Exception):
    """Raised when primary material alone exceeds the rendering budget."""


# 0.8 × 150_000 tokens × 4 chars/token ≈ 480_000.
_DEFAULT_MAX_CHARS = 480_000
_YOUR_TASK_BOILERPLATE = (
    "Produce the evolved deliverable based on the prior material and the "
    "user feedback. Do not re-derive material that is already present "
    "above; build on it. Use the reference material only if the primary "
    "material has a gap the feedback asks to fill."
)


def render_continuation_prefix(
    bundle: ContinuationBundle,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    primary = _render_primary(bundle.primary_materials)
    footer = _render_footer(bundle.user_feedback)

    # If primary alone is over budget, refuse.
    if len(primary) + len(footer) > max_chars:
        raise ContinuationBudgetError(
            "primary material exceeds rendering budget — split the continuation "
            "task or remove non-essential primary entries"
        )

    # Try full form first.
    refs_full = _render_references(bundle.reference_paths, full=True)
    full = _assemble(primary, refs_full, footer)
    if len(full) <= max_chars:
        return full

    # Fall back to metadata-only references.
    refs_stubs = _render_references(bundle.reference_paths, full=False)
    medium = _assemble(primary, refs_stubs, footer)
    if len(medium) <= max_chars:
        return medium

    # Last resort: drop references entirely.
    return _assemble(primary, "", footer)


def _render_primary(entries: list[BundleEntry]) -> str:
    parts = ["## Continuation Context", "", "### Prior deliverable (primary)", ""]
    for e in entries:
        parts.append(f"#### {e.source_task} / {e.relative_path}")
        parts.append("")
        parts.append(e.content_text)
        parts.append("")
    return "\n".join(parts)


def _render_references(refs: list[ReferencePointer], *, full: bool) -> str:
    if not refs:
        return ""
    parts = ["### Reference material (available via fs.read)", ""]
    for r in refs:
        line = f"- {r.source_task} / {r.relative_path} ({r.size_bytes} bytes)"
        if full and r.summary_head:
            head = r.summary_head.replace("\n", " ")[:200]
            line += f" — head: {head}"
        parts.append(line)
    parts.append("")
    return "\n".join(parts)


def _render_footer(user_feedback: str) -> str:
    return (
        "## User Feedback\n\n"
        f"{user_feedback}\n\n"
        "## Your Task\n\n"
        f"{_YOUR_TASK_BOILERPLATE}\n"
    )


def _assemble(primary: str, refs: str, footer: str) -> str:
    parts = [primary]
    if refs:
        parts.append(refs)
    parts.append(footer)
    return "\n".join(parts)
```

- [ ] **Step 4: Verify**

```
pytest packages/awp-runtime/tests/test_continuation_prompt_injection.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/awp-runtime/src/awp/continuation/prompt_injection.py packages/awp-runtime/tests/test_continuation_prompt_injection.py
git commit -m "feat(runtime): continuation prefix rendering + context-budget fallbacks"
```

---

## Task 3: Lift the continuation gate in the CLI validator

**Files:**
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_run_continuation_cli.py`

**Background.** Plan 2 Task 1 rejects `--target <cont>` with "continuation task runs are not yet supported". Plan 3 lifts that gate: continuation tasks pass validation and are dispatched to the new handler branch (Task 4).

- [ ] **Step 1: Write the failing test**

Create `packages/awp-core/tests/cli/test_run_continuation_cli.py`:

```python
"""CLI-level tests for `awp run --target <continuation>`."""

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
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def test_run_continuation_no_longer_rejected(env: dict, tmp_path: Path) -> None:
    """Continuation target is accepted (previously blocked in Plan 2 Task 1)."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]

    # Build a BEST dir so continuation creation passes
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"fake"}')
    (best / "paper.md").write_text("prior draft")

    r = _run_cli(
        [
            "task", "create", exp_id, "improve",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    env2 = env.copy()
    env2["AWP_RUN_TASK_DRY_RUN"] = "1"

    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml",
            "--task", "dummy",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    # The validator no longer rejects continuation tasks.
    # The dry-run branch prints the output_dir and exits 0.
    combined = r.stdout + r.stderr
    assert r.returncode == 0, combined
    assert "continuation" not in combined.lower() or "mode=continuation" not in combined.lower()
    assert str(tmp_path / exp_id / "tasks" / cont_id / "seed") in combined
```

- [ ] **Step 2: Run — expect failure (validator still rejects)**

```
pytest packages/awp-core/tests/cli/test_run_continuation_cli.py -v
```

- [ ] **Step 3: Lift the gate in `validate_task_key_for_run`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, find the `validate_task_key_for_run` function (added in Plan 2 Task 1). **Remove** the `if manifest.mode.value == "continuation"` block entirely:

```python
def validate_task_key_for_run(task_key: str) -> int:
    """Validate --target argument for `awp run`. Returns 0 on OK, non-zero on error."""
    if ":" not in task_key:
        print(
            "--task must be <experiment_id>:<task_id>",
            file=sys.stderr,
        )
        return 2
    exp_id, tid = task_key.split(":", 1)
    from awp.experiment.paths import experiment_dir as _exp_dir
    if not _exp_dir(exp_id).exists():
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
```

The error message "must be <experiment_id>:<task_id>" stays (the existing test `test_run_rejects_malformed_task_key` still expects that string).

- [ ] **Step 4: Update the Plan 2 continuation-rejection test**

Find `packages/awp-core/tests/cli/test_run_task_cli.py::test_run_rejects_continuation_task`. This test was asserting the Plan-2 behaviour that is now lifted. Replace its body (keeping the function and fixture setup) with a simple assertion that `--target <cont>` no longer rejects **at validation time**:

```python
def test_run_rejects_continuation_task(env: dict, tmp_path: Path) -> None:
    """Plan 3: continuation targets are accepted by the validator.

    The dispatch path (run_task_aware) is exercised in
    test_run_continuation_cli.py::test_run_continuation_no_longer_rejected.
    """
    # Build exp + seed + fake BEST + continuation task
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text("{}")
    r = _run_cli(
        [
            "task", "create", exp_id, "fb",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    env2 = env.copy()
    env2["AWP_RUN_TASK_DRY_RUN"] = "1"
    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml", "--task", "dummy",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    # Validator no longer rejects — dry-run exits 0
    assert r.returncode == 0, r.stderr + r.stdout
```

- [ ] **Step 5: Verify**

```
pytest packages/awp-core/tests/cli/test_run_task_cli.py packages/awp-core/tests/cli/test_run_continuation_cli.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_run_task_cli.py packages/awp-core/tests/cli/test_run_continuation_cli.py
git commit -m "feat(cli): lift continuation gate in validate_task_key_for_run"
```

---

## Task 4: Wire continuation dispatch in `run_task_aware`

**Files:**
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_run_continuation_cli.py` (extend)

**Background.** The handler must detect `mode=="continuation"`, call the bundle loader, render the prefix, and pass it as `manager_prompt_prefix` to `AgentWorkflow`. For seed tasks, the existing path stays (no prefix).

**Precondition to verify first.** `AgentWorkflow.__init__` accepts `manager_prompt_prefix: str | None = None`. Confirm with:

```
grep -n "manager_prompt_prefix" packages/awp-runtime/src/awp/data/workflow.py | head -5
```

If the parameter is absent, STOP and escalate — Plan 3 assumes this parameter exists based on Plan 2's exploration. Do NOT add it to `AgentWorkflow` without the user confirming.

- [ ] **Step 1: Write the failing test — mocked AgentWorkflow to capture kwargs**

Append to `packages/awp-core/tests/cli/test_run_continuation_cli.py`:

```python
def test_continuation_dispatch_passes_prefix_to_agentworkflow(
    env: dict, tmp_path: Path, monkeypatch
) -> None:
    """Verify that continuation mode calls AgentWorkflow with manager_prompt_prefix set."""
    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]

    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"fake"}')
    (best / "paper.md").write_text("prior draft body")

    r = _run_cli(
        [
            "task", "create", exp_id, "deepen section 2",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # Use a runtime hook that captures AgentWorkflow kwargs and exits before LLM
    env2 = env.copy()
    env2["AWP_CONTINUATION_CAPTURE_ONLY"] = str(tmp_path / "captured_kwargs.json")

    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml",
            "--task", "fallback",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    captured = json.loads((tmp_path / "captured_kwargs.json").read_text())
    prefix = captured["manager_prompt_prefix"]
    assert "## Continuation Context" in prefix
    assert "paper.md" in prefix
    assert "prior draft body" in prefix
    assert "deepen section 2" in prefix
    # Confirm AgentWorkflow also got output_dir pointing at the continuation task's seed
    assert captured["output_dir"].endswith(f"{cont_id}/seed")
    # Task text becomes the user_feedback for continuation
    assert captured["task"] == "deepen section 2"
```

- [ ] **Step 2: Run — expect failure**

```
pytest packages/awp-core/tests/cli/test_run_continuation_cli.py -v
```

- [ ] **Step 3: Extend `run_task_aware`**

In `packages/awp-core/src/awp/experiment/cli_handlers.py`, modify `run_task_aware` to branch on `manifest.mode`:

```python
def run_task_aware(args) -> int:
    """Handle `awp run --target <exp>:<task_id>` by delegating to AgentWorkflow."""
    from awp.experiment.paths import task_dir as _task_dir

    exp_id, tid = args.target.split(":", 1)
    td = _task_dir(exp_id, tid)
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
        from awp.experiment.paths import experiment_dir as _exp_dir
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
```

- [ ] **Step 4: Verify**

```
pytest packages/awp-core/tests/cli/test_run_continuation_cli.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run the full CLI suite**

```
pytest packages/awp-core/tests/cli/ -v 2>&1 | tail -15
```

Expected: all green (seed + continuation both work).

- [ ] **Step 6: Commit**

```bash
git add packages/awp-core/src/awp/experiment/cli_handlers.py packages/awp-core/tests/cli/test_run_continuation_cli.py
git commit -m "feat(cli): continuation dispatch — load bundle + pass prefix to AgentWorkflow"
```

---

## Task 5: Extend `_post_run_finalise` to record run_role for continuation runs

**Files:**
- Modify: `packages/awp-core/src/awp/experiment/cli_handlers.py`
- Test:   `packages/awp-core/tests/cli/test_run_continuation_cli.py` (extend)

**Background.** Plan 2's `_post_run_finalise` hard-codes `run_role="seed"`. For a continuation task's run, the role is still "seed" (the continuation is a seed-like run of a continuation task). But BEST is per-task, not per-mode, so the finaliser logic stays the same. **No code change is strictly needed** — but a test should prove that a continuation run's DB row + BEST lands correctly.

- [ ] **Step 1: Write the test**

Append to `packages/awp-core/tests/cli/test_run_continuation_cli.py`:

```python
def test_post_run_finalise_updates_continuation_best(
    env: dict, tmp_path: Path
) -> None:
    """A continuation task's run also lands BEST/ and DB row like a seed run."""
    import os as _os
    _os.environ["AWP_EXPERIMENTS_ROOT"] = env["AWP_EXPERIMENTS_ROOT"]
    _os.environ["AWP_UI_DB_PATH"] = env["AWP_UI_DB_PATH"]

    r = _run_cli(["experiment", "create", "E"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "seed"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    best.mkdir(parents=True)
    (best / "manifest.json").write_text('{"winner_run_id":"fake"}')
    (best / "paper.md").write_text("prior")

    r = _run_cli(
        [
            "task", "create", exp_id, "deepen",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # Build a fake finished run for the continuation task
    output_dir = tmp_path / exp_id / "tasks" / cont_id / "seed"
    run_id = "cont_run_1"
    run_dir = output_dir / "output" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "FINAL").mkdir()
    (run_dir / "FINAL" / "paper.md").write_text("improved draft")
    (run_dir / "events.jsonl").write_text("")
    (run_dir / "metrics.jsonl").write_text("")
    (run_dir / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "deepen",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 100, "cap": 1000}},
        "eval": {"score": 0.9},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))

    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=output_dir,
        run_id=run_id,
        exp_id=exp_id,
        task_key=f"{exp_id}:{cont_id}",
        task_text="deepen",
        model="m",
    )
    assert rc == 0

    # BEST for the continuation task
    best_manifest = output_dir.parent / "BEST" / "manifest.json"
    assert best_manifest.exists()
    m = json.loads(best_manifest.read_text())
    assert m["winner_run_id"] == run_id

    # DB row for the continuation run
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT task_id, run_role FROM runs WHERE id = ?", (run_id,),
    ).fetchone()
    con.close()
    assert row["task_id"] == f"{exp_id}:{cont_id}"
    assert row["run_role"] == "seed"  # continuation runs are still the "seed" run of the continuation task
```

- [ ] **Step 2: Run — should already pass (no code change needed)**

```
pytest packages/awp-core/tests/cli/test_run_continuation_cli.py::test_post_run_finalise_updates_continuation_best -v
```

If it fails, the failure points at a defect in `_post_run_finalise` — fix it there, not by splitting the code path.

- [ ] **Step 3: Commit**

```bash
git add packages/awp-core/tests/cli/test_run_continuation_cli.py
git commit -m "test(cli): verify continuation run lands BEST + DB row like seed"
```

---

## Task 6: R37 runtime-side enforcement note in the spec

**Files:**
- Modify: `spec/versions/1.0/validation-rules.md`

**Background.** R37 was normatively added in Plan 1 Task 12. It said enforcement is at "task-create time" (via Pydantic + CLI). Plan 3 adds a runtime-side enforcement path: `load_continuation_bundle` also refuses to load if the parent task has no `BEST/`. Update R37 to name this second enforcement point.

- [ ] **Step 1: Read the current R37 section**

```
sed -n '/R37/,/^### R/p' spec/versions/1.0/validation-rules.md | head -30
```

- [ ] **Step 2: Append a one-line enforcement note to the "Enforcement." block of R37**

Extend the existing enforcement paragraph to:

```markdown
**Enforcement.** Pydantic validator on `TaskManifest` (`packages/awp-core/src/awp/models/task.py`), the CLI handler in `packages/awp-core/src/awp/experiment/cli_handlers.py`, and — at run dispatch — the continuation bundle loader in `packages/awp-runtime/src/awp/continuation/bundle_loader.py` (which refuses to load a continuation whose `from_task` is missing a `BEST/manifest.json`).
```

- [ ] **Step 3: Verify drift gates**

```
python scripts/check_docs_drift.py && echo DRIFT_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 4: Commit**

```bash
git add spec/versions/1.0/validation-rules.md
git commit -m "docs(spec): R37 enforcement note — continuation bundle loader"
```

---

## Task 7: `docs/continuation.md` and CLAUDE.md

**Files:**
- Create: `docs/continuation.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write `docs/continuation.md`**

Create `docs/continuation.md` with the following content:

```markdown
# Continuation Mode (y-axis carry-over across tasks)

## What it is

Continuation mode lets a task reuse the prior task's deliverable as
starting material, combined with user feedback as the learning signal.
It is the runtime counterpart of the experiment-task hierarchy
(`docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md`)
for the user-task axis — distinct from refinement (`docs/refinement.md`,
y-optimisation within a single run) and outer-loop optimisation
(`docs/outer-loop.md`, θ-optimisation over prompt artifacts).

## Mental model

```
Task 001 (seed)  →  Task 001/BEST/paper.md
                         │
                         ▼
Task 002 (continuation, inputs=[{from_task:001,role:primary,bundle:BEST/}])
     user_feedback = "deepen section 2, add benchmarks"
     │
     ▼
  manager_prompt_prefix = render_continuation_prefix(bundle, feedback)
     │
     ▼
  AgentWorkflow(manager_prompt_prefix=…)
     │
     ▼ Task 002 Manager sees prior draft + feedback at iteration 1
  Task 002 produces evolved deliverable, NOT re-derived from scratch.
```

## Mechanism

1. **`task.json.inputs`** is non-empty (R37). Each entry has
   `from_task`, `role ∈ {primary, reference}`, and exactly one of
   `bundle: "BEST/"` or `paths: [...]`.
2. **`load_continuation_bundle(task_dir, experiment_dir)`** resolves
   each entry against `<experiment>/tasks/<from_task>/BEST/`. Primary
   entries inline the file contents; reference entries carry only
   path + size + first 200 chars.
3. **`render_continuation_prefix(bundle, max_chars=480_000)`** builds
   a deterministic prefix:
   - `## Continuation Context`
   - `### Prior deliverable (primary)` — each primary inlined
   - `### Reference material (available via fs.read)` — list, optionally dropped
   - `## User Feedback` — verbatim
   - `## Your Task` — build-on-prior boilerplate
4. **Budget fallback ladder.** Full → reference-stubs → no-reference →
   `ContinuationBudgetError` (primary alone over budget → split the task).
5. **CLI dispatch.** `awp run --target <exp>:<cont-task>` detects
   `mode=="continuation"`, calls the loader, renders the prefix, and
   passes it as `AgentWorkflow(manager_prompt_prefix=…)`. The
   `DelegationLoopRunner` (already plumbed for refinement) prepends
   the prefix to the Manager's iteration-1 user message.

## Relationship to refinement

Refinement (`docs/refinement.md`) also injects a prefix, but:
- Scope = one run, multiple iterations (y-axis within a run).
- Gradient = auto-extracted from critique + gate rejections + eval deltas.
- Prefix is applied to iteration 1 of the refinement session's run.

Continuation:
- Scope = task → next task (y-axis across tasks).
- Gradient = user-written feedback (free text).
- Prefix is applied to iteration 1 of the next task's seed run.

Both mechanisms can compose: a continuation task's seed run can also
be refined, and the refinement engine's prefix will overlay on top of
whatever state the continuation prefix produced in iteration 1.

## R37

Continuation tasks with empty `inputs` are rejected at task-create
time and at runtime (bundle loader refuses without BEST). See
`spec/versions/1.0/validation-rules.md`.

## Files

- `packages/awp-runtime/src/awp/continuation/bundle_loader.py` — `load_continuation_bundle`
- `packages/awp-runtime/src/awp/continuation/prompt_injection.py` — `render_continuation_prefix`
- `packages/awp-core/src/awp/experiment/cli_handlers.py` — CLI dispatch (`run_task_aware`)
```

- [ ] **Step 2: Extend `CLAUDE.md` Development Commands**

In the existing Development Commands block, replace the Plan-2 continuation comment ("continuation rejected — see Plan 3") with:

```
# Continuation task runs (Plan 3)
awp run <workflow_path> --task "<fallback>" --target <experiment_id>:<continuation_task_id>
  # Loads prior BEST bundle + user_feedback as manager_prompt_prefix.
  # --task here is a fallback string that only surfaces if AgentWorkflow
  # needs a task field for legacy reasons; the Manager's actual task is
  # user_feedback from task.json. See docs/continuation.md.
```

- [ ] **Step 3: Verify drift gates**

```
python scripts/check_docs_drift.py && echo DRIFT_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

- [ ] **Step 4: Commit**

```bash
git add docs/continuation.md CLAUDE.md
git commit -m "docs: continuation mechanism (y-axis carry-over across tasks)"
```

---

## Task 8: End-to-end shell smoke test (no LLM)

**Files:**
- Create: `packages/awp-runtime/tests/test_continuation_smoke.py`

**Background.** Plan 2 taught us that fixtures can silently disagree with production schemas. This task runs the continuation path through the real CLI (`subprocess.run`) with a fake-run shim, verifies the complete artefact-and-DB state, and catches schema mismatches end-to-end.

- [ ] **Step 1: Write the smoke test**

Create `packages/awp-runtime/tests/test_continuation_smoke.py`:

```python
"""End-to-end smoke test for the continuation pipeline (no LLM).

Exercises: CLI experiment+task CRUD → fake finished seed run →
fake finished continuation run → BEST promotion through both tasks.
Catches the "fixtures disagree with production schema" class of bug.
"""

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
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def env(tmp_path: Path) -> dict:
    env = os.environ.copy()
    env["AWP_EXPERIMENTS_ROOT"] = str(tmp_path)
    env["AWP_UI_DB_PATH"] = str(tmp_path / "awp_ui.db")
    return env


def _mk_fake_run(output_dir: Path, run_id: str, score: float) -> None:
    rd = output_dir / "output" / run_id
    rd.mkdir(parents=True)
    (rd / "FINAL").mkdir()
    (rd / "FINAL" / "paper.md").write_text(f"draft-from-{run_id}")
    (rd / "events.jsonl").write_text("")
    (rd / "metrics.jsonl").write_text("")
    (rd / "run_completion.json").write_text(json.dumps({
        "run_id": run_id,
        "status": "complete",
        "task": "t",
        "final_budget": {"loops": {"used": 1, "cap": 10}, "tokens": {"used": 1, "cap": 100}},
        "eval": {"score": score},
        "critique": {"defects": []},
        "gate_rejections": 0,
    }))


def test_seed_then_continuation_smoke(env: dict, tmp_path: Path) -> None:
    # 1. Experiment + seed task
    r = _run_cli(["experiment", "create", "Smoke"], env=env)
    exp_id = json.loads(r.stdout)["experiment_id"]
    r = _run_cli(["task", "create", exp_id, "Write paper"], env=env)
    seed_id = json.loads(r.stdout)["task_id"]
    seed_output = tmp_path / exp_id / "tasks" / seed_id / "seed"

    # 2. Fake a finished seed run + finalise
    _mk_fake_run(seed_output, "seed_run_1", score=0.9)
    import importlib
    cli_handlers = importlib.import_module("awp.experiment.cli_handlers")
    rc = cli_handlers._post_run_finalise(
        output_dir=seed_output,
        run_id="seed_run_1",
        exp_id=exp_id,
        task_key=f"{exp_id}:{seed_id}",
        task_text="Write paper",
        model="m",
    )
    assert rc == 0
    seed_best = tmp_path / exp_id / "tasks" / seed_id / "BEST"
    assert (seed_best / "paper.md").read_text() == "draft-from-seed_run_1"

    # 3. Continuation task
    r = _run_cli(
        [
            "task", "create", exp_id, "deepen section 2",
            "--continuation", "--from-task", seed_id, "--primary", "BEST/",
        ],
        env=env,
    )
    cont_id = json.loads(r.stdout)["task_id"]

    # 4. Exercise the CLI continuation path in CAPTURE_ONLY mode:
    #    ensures the bundle + prefix were built correctly before any LLM call
    capture = tmp_path / "captured.json"
    env2 = env.copy()
    env2["AWP_CONTINUATION_CAPTURE_ONLY"] = str(capture)
    r = _run_cli(
        [
            "run", "nonexistent-wf.yaml",
            "--task", "ignored",
            "--target", f"{exp_id}:{cont_id}",
        ],
        env=env2,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    cap = json.loads(capture.read_text())
    assert cap["mode"] == "continuation"
    assert "## Continuation Context" in cap["manager_prompt_prefix"]
    assert "draft-from-seed_run_1" in cap["manager_prompt_prefix"]
    assert "deepen section 2" in cap["manager_prompt_prefix"]
    assert cap["task"] == "deepen section 2"

    # 5. Fake a finished continuation run + finalise
    cont_output = tmp_path / exp_id / "tasks" / cont_id / "seed"
    _mk_fake_run(cont_output, "cont_run_1", score=0.95)
    rc = cli_handlers._post_run_finalise(
        output_dir=cont_output,
        run_id="cont_run_1",
        exp_id=exp_id,
        task_key=f"{exp_id}:{cont_id}",
        task_text="deepen section 2",
        model="m",
    )
    assert rc == 0

    # 6. BEST for the continuation task
    cont_best = tmp_path / exp_id / "tasks" / cont_id / "BEST"
    assert (cont_best / "manifest.json").exists()
    m = json.loads((cont_best / "manifest.json").read_text())
    assert m["winner_run_id"] == "cont_run_1"

    # 7. DB state: both runs present with correct task_id
    import sqlite3
    con = sqlite3.connect(env["AWP_UI_DB_PATH"])
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, task_id FROM runs WHERE experiment_id = ? ORDER BY id",
        (exp_id,),
    ).fetchall()
    con.close()
    assert {r["id"] for r in rows} == {"seed_run_1", "cont_run_1"}
    assert dict((r["id"], r["task_id"]) for r in rows) == {
        "seed_run_1": f"{exp_id}:{seed_id}",
        "cont_run_1": f"{exp_id}:{cont_id}",
    }
```

- [ ] **Step 2: Run and verify**

```
pytest packages/awp-runtime/tests/test_continuation_smoke.py -v
```

Expected: 1 test passed.

If it fails, the failure points at a schema mismatch between the
continuation pipeline's expectations and the fake run artefacts. Fix
the fake artefact to match reality (as in Plan 2's `eval`/`evaluation`
fix) — do NOT silence the test.

- [ ] **Step 3: Commit**

```bash
git add packages/awp-runtime/tests/test_continuation_smoke.py
git commit -m "test(runtime): smoke-test for seed→continuation pipeline (no LLM)"
```

---

## Task 9: Mirror sync + full regression

**Files:**
- Sync: `reference/python/src/awp/continuation/` + updated `cli_handlers.py`

- [ ] **Step 1: Full regression**

```
pytest packages/awp-core/tests/ packages/awp-runtime/tests/ -k "not e2e" 2>&1 | tail -5
```

Expected: all green except the 1 pre-existing `test_manager_prompt_uses_default_worker_pitfalls`.

- [ ] **Step 2: Sync the mirror**

```
rsync -a packages/awp-core/src/awp/ reference/python/src/awp/
rsync -a packages/awp-runtime/src/awp/ reference/python/src/awp/
rsync -a packages/awp-ui/server/ reference/python/src/server/
```

- [ ] **Step 3: Verify all three drift gates**

```
python scripts/check_mirror_drift.py && echo MIRROR_OK
python scripts/check_docs_drift.py && echo DOCS_OK
python scripts/check_sync_coverage.py && echo SYNC_OK
```

All three must print the OK line.

- [ ] **Step 4: Commit**

```bash
git add reference/python/src/
git commit -m "chore(mirror): sync reference/python/src with Plan 3 (continuation)"
```

---

## Self-review checklist

Before declaring Plan 3 complete:

- `awp run --target <cont>` no longer rejects at validation time.
- `load_continuation_bundle` refuses when the parent task has no `BEST/` (runtime-side R37).
- `render_continuation_prefix` produces a deterministic string and never raises `ContinuationBudgetError` unless primary alone overflows.
- `AgentWorkflow` is called with `manager_prompt_prefix=<prefix>` for continuation targets (verified by capture-mode test).
- The continuation task's DB row lands with `run_role="seed"` and the right `task_id`.
- BEST finaliser works uniformly for seed and continuation runs.
- `docs/continuation.md` exists and is one-hop-reachable from other architecture docs.
- All three drift gates are green.

---

## Handoff to Plan 4

At the end of Plan 3 the core Experiment-Task-Continuation flow works end-to-end (minus real-LLM E2E, which is a separate follow-up). Plan 4 picks up:
- `awp refine --task <exp>:<task>` → relocate refinement iterations under `<task>/refinements/session_<ts>/`.
- `awp optimize --task <exp>:<task>` → open `<experiment>/outer_loop.db` (per-experiment isolation, decision β) and write epoch-runs under `<task>/optimizations/suite_<ts>/`.
- Continuation + refine composition: refining inside a continuation task.
