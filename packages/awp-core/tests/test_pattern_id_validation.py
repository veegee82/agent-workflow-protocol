"""Tests for Fix F — pattern_id validation hints on R31.

* R31 rejections for unknown / missing ``pattern_id`` MUST include the
  full sorted list of known pattern_ids in the error payload so the
  manager can self-correct on the next turn.
* R31 rejections MUST also surface the archetype alternative.
"""

from __future__ import annotations

from awp.validator.rules_planning import validate_runtime_plan


def test_unknown_pattern_id_includes_known_list():
    plan = {
        "decision": "plan",
        "subtasks": [
            {
                "id": "s1",
                "description": "render report",
                "success_criteria": "report exists",
                "assumptions": [],
                "tool_manifest": [
                    {
                        "subtask": "s1",
                        "capability": "markdown_report",
                        "reuse_or_generate": "reuse",
                        "pattern_id": "markdown_report",  # close but wrong
                    }
                ],
            }
        ],
    }
    violations = validate_runtime_plan(plan)
    assert violations, "expected at least one violation"
    msg = "\n".join(violations)
    assert "markdown_report" in msg  # the rejected id is echoed
    # The full known list is surfaced so the manager can pick the real id.
    assert "markdown_report_writer" in msg
    # The archetype alternative is surfaced too (prompt escape hatch).
    assert "archetype_id" in msg or "synthesize" in msg


def test_missing_pattern_id_also_lists_known_ids():
    plan = {
        "decision": "plan",
        "subtasks": [
            {
                "id": "s1",
                "description": "render report",
                "success_criteria": "report exists",
                "assumptions": [],
                "tool_manifest": [
                    {
                        "subtask": "s1",
                        "capability": "markdown_report",
                        "reuse_or_generate": "reuse",
                        # pattern_id intentionally omitted
                    }
                ],
            }
        ],
    }
    violations = validate_runtime_plan(plan)
    msg = "\n".join(violations)
    assert "missing 'pattern_id'" in msg
    assert "markdown_report_writer" in msg
    assert "synthesize" in msg


def test_prompt_contains_dynamic_pattern_id_list():
    """The manager-side plan prompt must include the live pattern_id
    registry so the manager never has to guess a name."""
    try:
        from awp.data.prompts import build_manager_system_prompt
        from awp.patterns import PATTERNS
    except ImportError:
        # awp-runtime not installed → test is scoped to awp-core only
        import pytest

        pytest.skip("awp-runtime not installed")

    prompt = build_manager_system_prompt(
        input_manifest={},
        sandbox_type="subprocess",
        forbidden_tools=["shell.execute"],
        max_tools_per_worker=10,
    )
    for pid in PATTERNS.keys():
        assert pid in prompt, f"known pattern_id '{pid}' missing from prompt"
    # Hint about the escape hatch must be present so the manager knows
    # what to do when no concrete pattern_id fits.
    assert "synthesize" in prompt
    assert "archetype_id" in prompt
