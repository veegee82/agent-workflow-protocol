"""Tests for AWP Framework-Fix gamma: deterministic atomicity score.

These tests lock in the calibration of the heuristic described in
``awp.runtime.atomicity``. If you retune the weights there, update the
expectations here — the constants exist to serve concrete target scores,
not the other way around.
"""

from __future__ import annotations

from awp.runtime.atomicity import (
    atomicity_advisory_line,
    atomicity_score,
)
from awp.runtime.delegation_loop_runner import TaskPlan


def test_atomic_subtask_scores_high() -> None:
    """A short, atomic read/count task must score >= 0.75."""
    subtask = {
        "id": "st_atomic",
        "description": "Read CLAUDE.md and return its word count.",
        "status": "pending",
    }
    score = atomicity_score(subtask)
    assert score >= 0.75, (
        f"Expected atomic subtask to score >= 0.75, got {score:.4f}"
    )


def test_composite_subtask_scores_low() -> None:
    """A long, composition-heavy task with many outputs must score <= 0.3."""
    subtask = {
        "id": "st_composite",
        "description": (
            "Analyze the entire repository architecture. Coordinate multiple "
            "analysis workers to orchestrate a systematic review. Assemble a "
            "comprehensive multi-file report that integrates findings from "
            "various sources. Synthesize the results into cohesive "
            "documentation with citations, cross-references, diagrams, and "
            "an executive summary. Delegate individual analysis slices to "
            "specialist workers and integrate their outputs into the final "
            "deliverable structure."
        ),
        "required_outputs": [
            f"report_{i}.md" for i in range(1, 11)
        ],  # 10 required outputs
        "success_criteria": (
            "All 10 report files exist and the integrated summary references "
            "each."
        ),
        "status": "pending",
    }
    score = atomicity_score(subtask)
    assert score <= 0.30, (
        f"Expected composite subtask to score <= 0.30, got {score:.4f}"
    )


def test_score_is_deterministic() -> None:
    """Same input twice -> identical score (no RNG, no hidden state)."""
    subtask = {
        "description": "Parse the CSV at inputs/data.csv and extract the top 5 rows.",
        "required_outputs": ["top5.csv"],
    }
    s1 = atomicity_score(subtask)
    s2 = atomicity_score(subtask)
    assert s1 == s2, f"Non-deterministic score: {s1} != {s2}"


def test_score_bounds() -> None:
    """Score must always lie in [0.0, 1.0] for any reasonable input."""
    cases: list[dict] = [
        {},
        {"description": ""},
        {"description": "x"},
        {"description": "read " * 500},  # keyword spam
        {
            "description": "coordinate " * 500,
            "required_outputs": [f"f{i}" for i in range(100)],
        },
        {"description": None},  # type: ignore[dict-item]
        {"required_outputs": None},  # type: ignore[dict-item]
        {"required_outputs": "single_output.md"},
    ]
    for case in cases:
        score = atomicity_score(case)
        assert 0.0 <= score <= 1.0, f"Out-of-bounds score {score} for {case!r}"


def test_missing_fields_neutral() -> None:
    """Empty / missing subtask collapses to the neutral band around 0.5."""
    score = atomicity_score({})
    assert 0.4 <= score <= 0.7, (
        f"Empty subtask should be neutral-ish, got {score:.4f}"
    )


def test_accepts_object_style_subtask() -> None:
    """Pydantic-style objects with ``model_dump`` or attributes work too."""

    class ObjSubtask:
        def __init__(self) -> None:
            self.description = "Read inputs.csv and count the rows."
            self.required_outputs: list[str] = []
            self.success_criteria = "Row count is printed."

    score = atomicity_score(ObjSubtask())
    assert 0.0 <= score <= 1.0
    # Two atomic keywords (read, count) -> should still skew atomic-ish.
    assert score >= 0.6


def test_advisory_line_wording() -> None:
    """Advisory line always mentions 'atomicity score' and a formatted value."""
    subtask = {"description": "Read the file and count its words."}
    line = atomicity_advisory_line(subtask)
    assert "atomicity score" in line.lower()
    # 2-decimal formatted value must be present in the line.
    score = atomicity_score(subtask)
    assert f"{score:.2f}" in line


def test_score_used_in_prompt() -> None:
    """The plan's prompt section must include the atomicity advisory line."""
    plan = TaskPlan()
    plan.set_subtasks(
        [
            {
                "id": "st1",
                "description": "Read CLAUDE.md and count its words.",
                "priority": "normal",
                "dependencies": [],
            },
            {
                "id": "st2",
                "description": (
                    "Coordinate and orchestrate assembly of a multi-file "
                    "synthesis report with citations and diagrams."
                ),
                "priority": "high",
                "dependencies": [],
                "required_outputs": [
                    "a.md", "b.md", "c.md", "d.md", "e.md",
                ],
            },
        ]
    )
    section = plan.to_prompt_section()
    assert "atomicity score" in section.lower(), (
        "Plan prompt section must surface the atomicity advisory"
    )
    # At least the two pending subtask ids should be present.
    assert "st1" in section and "st2" in section
    # The advisory block header must be present exactly once.
    assert section.lower().count("atomicity advisories") == 1


def test_completed_subtasks_not_advised() -> None:
    """Advisories are only for pending subtasks, not completed ones."""
    plan = TaskPlan()
    plan.set_subtasks(
        [
            {
                "id": "st_done",
                "description": "Read the file and count its words.",
                "priority": "normal",
                "dependencies": [],
            },
            {
                "id": "st_pending",
                "description": "Parse the CSV and extract rows.",
                "priority": "normal",
                "dependencies": [],
            },
        ]
    )
    # Mark st_done as completed via the public update_status API.
    plan.update_status("st_done", "completed", result_summary="ok")

    section = plan.to_prompt_section()
    # Advisory block must exist and mention the pending one, but the
    # completed one must NOT appear in the advisory block itself.
    # (It still appears in the plan-progress table — that is fine.)
    assert "atomicity advisories" in section.lower()
    advisory_block = section.lower().split("atomicity advisories", 1)[1]
    assert "st_pending" in advisory_block
    assert "st_done" not in advisory_block
