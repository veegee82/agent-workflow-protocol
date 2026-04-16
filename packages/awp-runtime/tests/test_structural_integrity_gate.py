"""Tests for the structural-integrity gate in DelegationLoopRunner.

The gate is the last line of defence before a manager can declare a
run `complete`: it catches cheat-to-complete moves that the
placeholder/file gates miss — stacked orphan anchors, mixed-format
references, duplicated paragraph filler, figure captions without
inline body references. Each check is exercised in isolation and one
test confirms the gate stays silent on a clean deliverable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from awp.runtime.delegation_loop_runner import DelegationLoopRunner


@pytest.fixture
def runner(tmp_path: Path) -> DelegationLoopRunner:
    """Minimal runner stub with just enough plumbing for the structural
    check. The method under test only reads from ``self._dir`` and
    ``self._run_id`` — bypass ``__init__`` to avoid wiring the rest of
    the delegation loop."""
    r = DelegationLoopRunner.__new__(DelegationLoopRunner)
    run_id = "2026-04-14_00-00-00_test"
    r._dir = tmp_path
    r._run_id = run_id
    (tmp_path / "output" / run_id).mkdir(parents=True)
    r._logger = MagicMock()
    return r


def _write(runner: DelegationLoopRunner, name: str, content: str) -> Path:
    p = runner._dir / "output" / runner._run_id / name
    p.write_text(content, encoding="utf-8")
    return p


def test_clean_paper_passes(runner):
    _write(runner, "paper.md", (
        "# Great Paper\n\n"
        "**Authors:** A. B.\n\n"
        "<a id=\"intro\"></a>\n"
        "## Introduction\n\n"
        "This is a well-formed introduction paragraph with enough length "
        "to be considered a real paragraph rather than a boilerplate stub. "
        "It contains at least one hundred and twenty characters.\n\n"
        "<a id=\"method\"></a>\n"
        "## Method\n\n"
        "The method section is distinct from the introduction. See "
        "Figure 1 for an overview.\n\n"
        "![fig](figs/figure1.png)\n\n"
        "**Figure 1:** Overview.\n\n"
        "## References\n\n"
        "[1] Author. Title. Venue, 2020.\n"
    ))
    assert runner._check_structural_integrity() == []


def test_stacked_orphan_anchors_fail(runner):
    body = "# Title\n\n" + ("word " * 40 + "\n\n") * 6
    tail = "\n".join(f'<a id="sec-{i}"></a>' for i in range(6))
    _write(runner, "paper.md", body + tail)
    failures = runner._check_structural_integrity()
    assert any("not adjacent" in f for f in failures)


def test_mixed_reference_format_fails(runner):
    _write(runner, "paper.md", (
        "# Title\n\n"
        "Body uses legacy style [ref_Foo123] and [ref_Bar456] cites.\n\n"
        + ("Additional body paragraph padding the file past the "
           "500-char structural-gate threshold so the check actually "
           "runs. This sentence adds more characters. ") * 3
        + "\n\n## References\n\n"
        "[1] Author A. Real ref. Venue, 2020.\n"
        "[2] Author B. Another. Venue, 2021.\n"
        "[3] Author C. Third. Venue, 2022.\n"
    ))
    failures = runner._check_structural_integrity()
    assert any("mixed reference format" in f for f in failures)


def test_duplicated_paragraphs_fail(runner):
    dup = (
        "This paragraph is identical and is duplicated repeatedly as the "
        "kind of filler workers emit when they cannot think of new "
        "content to write into the draft deliverable."
    )
    distinct = [
        f"Distinct paragraph number {i} with enough unique characters to "
        f"not collide with any other paragraph in this synthetic document."
        for i in range(2)
    ]
    paragraphs = [dup] * 5 + distinct  # 5/7 duplicates = 71%
    _write(runner, "paper.md", "# Title\n\n" + "\n\n".join(paragraphs))
    failures = runner._check_structural_integrity()
    assert any("duplicates of earlier" in f for f in failures)


def test_figure_caption_without_inline_reference_fails(runner):
    _write(runner, "paper.md", (
        "# Title\n\n"
        + ("Padding paragraph to exceed the 500-char minimum, with "
           "enough words to look like real prose rather than a stub. "
           "A second sentence to be safe. ") * 3
        + "\n\n![fig](figs/figure1.png)\n\n"
        "**Abbildung 1:** Beispielhafte Illustration.\n"
    ))
    failures = runner._check_structural_integrity()
    assert any("figure caption(s) present but no inline" in f for f in failures)


def test_no_markdown_no_failures(runner):
    # CSV-only deliverable must not spuriously fail the gate.
    _write(runner, "data.csv", "col1,col2\n" + "1,2\n" * 50)
    assert runner._check_structural_integrity() == []
