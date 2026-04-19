"""Tests for the Phase 3.3 canonical output pointer (``output/FINAL/``).

The helper :meth:`DelegationLoopRunner._write_canonical_final_output` is
a pure filesystem operation driven by
:meth:`DelegationLoopRunner._derive_required_deliverables`. Both methods
only read instance attributes (``self._dir``, ``self._run_id``,
``self._task_plan``) and do no I/O outside the workflow tree, so we can
exercise them against a hand-assembled lightweight stub instead of
spinning up a real LLM-driven delegation loop.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from awp.runtime.delegation_loop_runner import DelegationLoopRunner


def _invoke_final_writer(runner, task: str = "create paper.pdf") -> None:
    """Bypass ``__init__`` and call the method under test directly.

    The method is a regular bound method, so we can unbind it and pass
    the stub as ``self``. This keeps the test hermetic — no LLM client,
    no critique engine, no signal handler.
    """
    DelegationLoopRunner._write_canonical_final_output(runner, task)


class _StubTaskPlan:
    """Minimal stand-in for :class:`TaskPlan` — exposes ``_subtasks``."""

    def __init__(self, subtasks: list[dict]) -> None:
        self._subtasks = subtasks


def _make_runner_stub(
    tmp_path: Path,
    *,
    run_id: str = "run-root",
    required_outputs: list[str] | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace carrying the attributes and methods the
    FINAL-writer reaches for. ``_derive_required_deliverables`` is
    imported as an unbound method and bound to the stub so the real
    priority-1 → priority-2 → empty logic runs exactly as production.
    """
    subtasks: list[dict] = []
    if required_outputs:
        subtasks.append(
            {
                "id": "t1",
                "description": "produce the deliverable",
                "required_outputs": list(required_outputs),
            }
        )
    stub = SimpleNamespace(
        _dir=tmp_path,
        _run_id=run_id,
        _task_plan=_StubTaskPlan(subtasks) if subtasks else None,
        # Class-level regex used by priority-2 regex scraping — the
        # unbound method resolves it via ``self._DELIVERABLE_PATH_RE``.
        _DELIVERABLE_PATH_RE=DelegationLoopRunner._DELIVERABLE_PATH_RE,
    )
    # Borrow the real unbound method from the class so we exercise the
    # production priority resolution (required_outputs > success_criteria
    # > empty) without pulling in the full runner constructor.
    stub._derive_required_deliverables = lambda task: (
        DelegationLoopRunner._derive_required_deliverables(stub, task)
    )
    return stub


# ---------------------------------------------------------------------------
# (a) Multiple sub-manager outputs: deepest valid instance wins
# ---------------------------------------------------------------------------


def test_final_pointer_promotes_deepest_non_empty_instance(tmp_path):
    """When multiple candidates for ``paper.pdf`` exist under output/,
    the deepest non-empty copy (e.g. inside a sub-manager's run dir)
    must win over a shallower stub."""
    # Root manager wrote a small stub at output/<root_run>/paper.pdf
    root_run_dir = tmp_path / "output" / "run-root"
    root_run_dir.mkdir(parents=True, exist_ok=True)
    root_copy = root_run_dir / "paper.pdf"
    root_copy.write_bytes(b"STUB PDF")

    # Sub-manager wrote the real content deeper in the tree.
    submgr_dir = tmp_path / "output" / "run-submgr-a" / "nested"
    submgr_dir.mkdir(parents=True, exist_ok=True)
    sub_copy = submgr_dir / "paper.pdf"
    real_content = b"%PDF-1.4 real content with lots of bytes" * 40
    sub_copy.write_bytes(real_content)

    # And a second sub-manager also produced one.
    submgr2_dir = tmp_path / "output" / "run-submgr-b"
    submgr2_dir.mkdir(parents=True, exist_ok=True)
    (submgr2_dir / "paper.pdf").write_bytes(b"%PDF-1.4 alt content")

    runner = _make_runner_stub(tmp_path, required_outputs=["paper.pdf"])
    _invoke_final_writer(runner, task="Create paper.pdf")

    final = tmp_path / "output" / "FINAL" / "paper.pdf"
    assert final.is_file(), list((tmp_path / "output").rglob("*"))
    # The deepest instance (submgr-a/nested) wins — 3 parts deep vs. 2.
    assert final.read_bytes() == real_content

    # De-duplication: exactly one file under FINAL/ (not three).
    final_files = [p for p in (tmp_path / "output" / "FINAL").rglob("*") if p.is_file()]
    assert len(final_files) == 1


# ---------------------------------------------------------------------------
# (b) No deliverable declared → FINAL/ is NOT created
# ---------------------------------------------------------------------------


def test_final_pointer_skipped_when_no_deliverable(tmp_path):
    """With no ``required_outputs`` on the plan (and no extractable
    ``_output_dir`` token in the task text), the method must leave
    ``output/FINAL/`` uncreated — an empty FINAL/ would lie to the UI
    about what the run delivered.
    """
    # Some output exists but nothing was declared a deliverable.
    run_dir = tmp_path / "output" / "run-root"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scratch.txt").write_text("not a declared deliverable")

    runner = _make_runner_stub(tmp_path, required_outputs=None)
    _invoke_final_writer(runner, task="free-form task with no file name")

    final = tmp_path / "output" / "FINAL"
    assert not final.exists()


# ---------------------------------------------------------------------------
# Sanity — empty candidate set (declared deliverable, but no file found
# anywhere) still leaves FINAL/ uncreated.
# ---------------------------------------------------------------------------


def test_final_pointer_skipped_when_declared_file_missing(tmp_path):
    """A deliverable declared in the plan but never produced by any
    worker must not cause a spurious FINAL/ entry."""
    # Output dir exists but the declared deliverable is not in it.
    (tmp_path / "output" / "run-root").mkdir(parents=True, exist_ok=True)

    runner = _make_runner_stub(tmp_path, required_outputs=["never_written.pdf"])
    _invoke_final_writer(runner, task="Create never_written.pdf")

    final = tmp_path / "output" / "FINAL"
    # Either absent or empty — both are acceptable contracts. The method
    # explicitly returns before mkdir when the candidate set is empty, so
    # we expect absent here.
    assert not final.exists()
