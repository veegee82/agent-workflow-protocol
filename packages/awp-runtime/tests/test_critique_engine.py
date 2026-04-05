"""Tests for the Reflective Critique Loop engine."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from awp.runtime.critique.models import (
    CritiqueEnvelope,
    Defect,
    PatternMemory,
    RepairAttempt,
)
from awp.runtime.critique.engine import CritiqueEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    enabled: bool = True,
    max_repair_attempts: int = 2,
    repair_budget_fraction: float = 0.15,
    pattern_memory: bool = True,
    mode: str = "inline",
    model: str | None = None,
):
    """Create a mock CritiqueConfig."""
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.mode = mode
    cfg.model = model
    cfg.max_repair_attempts = max_repair_attempts
    cfg.repair_budget_fraction = repair_budget_fraction
    cfg.pattern_memory = pattern_memory
    cfg.defect_categories = [
        "missing_data",
        "wrong_format",
        "incomplete",
        "hallucinated",
        "stale",
        "policy_violation",
    ]
    return cfg


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestDefect:
    def test_creation(self):
        d = Defect(
            category="missing_data",
            location="root.analysis",
            description="No analysis field",
            severity="critical",
        )
        assert d.category == "missing_data"
        assert d.severity == "critical"


class TestCritiqueEnvelope:
    def test_no_defects(self):
        c = CritiqueEnvelope(worker_id="w1", score=0.95, summary="Good")
        assert not c.has_critical_defects
        assert c.critical_count == 0
        assert c.warning_count == 0

    def test_critical_defects(self):
        c = CritiqueEnvelope(
            worker_id="w1",
            score=0.3,
            defects=[
                Defect("missing_data", "root.x", "missing x", "critical"),
                Defect("incomplete", "root.y", "empty y", "warning"),
                Defect("stale", "root.z", "old data", "critical"),
            ],
        )
        assert c.has_critical_defects
        assert c.critical_count == 2
        assert c.warning_count == 1

    def test_to_dict(self):
        c = CritiqueEnvelope(
            worker_id="w1",
            score=0.7,
            defects=[Defect("incomplete", "root.a", "half done", "warning")],
            prescriptions=["Complete field a"],
            reusable_patterns=["Workers often miss field a"],
            effort_estimate="trivial",
            summary="Minor issues",
        )
        d = c.to_dict()
        assert d["worker_id"] == "w1"
        assert d["score"] == 0.7
        assert len(d["defects"]) == 1
        assert d["critical_count"] == 0
        assert d["warning_count"] == 1


class TestPatternMemory:
    def test_record_and_retrieve(self):
        pm = PatternMemory()
        pm.record("missing_data", "Workers miss X", "Always include X", iteration=1)
        pm.record("missing_data", "Workers miss X again", "Always include X", iteration=2)
        pm.record("wrong_format", "Bad JSON", "Use valid JSON", iteration=2)

        rules = pm.get_prevention_rules()
        assert len(rules) == 2
        # Most frequent first
        assert "missing_data" in rules[0]
        assert "x2" in rules[0]

    def test_has_recurring_pattern(self):
        pm = PatternMemory()
        pm.record("stale", "Old cache", "Refresh cache", iteration=1)
        assert not pm.has_recurring_pattern("stale", min_frequency=2)
        pm.record("stale", "Still old", "Always refresh", iteration=2)
        assert pm.has_recurring_pattern("stale", min_frequency=2)

    def test_to_dict(self):
        pm = PatternMemory()
        pm.record("incomplete", "Half done", "Finish it", iteration=1)
        d = pm.to_dict()
        assert "incomplete" in d
        assert d["incomplete"]["frequency"] == 1


class TestRepairAttempt:
    def test_to_dict(self):
        r = RepairAttempt(
            worker_id="w1",
            attempt=1,
            original_score=0.3,
            repaired_score=0.8,
            defects_fixed=2,
            defects_remaining=0,
            critique_before=CritiqueEnvelope(worker_id="w1", score=0.3),
        )
        d = r.to_dict()
        assert d["original_score"] == 0.3
        assert d["repaired_score"] == 0.8
        assert d["defects_fixed"] == 2


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------


class TestCritiqueEngineDisabled:
    def test_disabled_returns_passthrough(self, tmp_path: Path):
        cfg = _make_config(enabled=False)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        result = engine.critique_result("w1", {"confidence": 0.9, "data": "ok"}, "task", {}, 1)
        assert result.score == 1.0
        assert result.summary == "Critique disabled"

    def test_enabled_property(self, tmp_path: Path):
        cfg = _make_config(enabled=False)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")
        assert not engine.enabled

        cfg2 = _make_config(enabled=True)
        engine2 = CritiqueEngine(cfg2, tmp_path, "test-run")
        assert engine2.enabled


class TestCritiqueEngineHeuristic:
    """Test the heuristic fallback (when LLM is unavailable)."""

    def test_missing_confidence(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        # Mock LLM to fail → triggers heuristic
        with patch.object(engine, "_run_critique", wraps=engine._heuristic_critique):
            result = engine._heuristic_critique("w1", {"data": "some data"}, {})
        assert result.has_critical_defects
        assert any(d.category == "missing_data" for d in result.defects)

    def test_error_in_result(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        result = engine._heuristic_critique(
            "w1", {"error": "something broke", "confidence": 0.1}, {}
        )
        assert result.has_critical_defects
        assert any(d.category == "incomplete" for d in result.defects)

    def test_missing_required_fields(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        envelope = {
            "output_contract": {
                "required_fields": ["analysis", "recommendations"],
            }
        }
        result = engine._heuristic_critique(
            "w1",
            {"confidence": 0.7},  # missing analysis and recommendations
            envelope,
        )
        assert result.has_critical_defects
        missing = [d for d in result.defects if d.category == "missing_data"]
        assert len(missing) >= 2

    def test_clean_result(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        result = engine._heuristic_critique(
            "w1",
            {"confidence": 0.85, "analysis": "Good analysis", "data": [1, 2, 3]},
            {"output_contract": {"required_fields": ["analysis", "data"]}},
        )
        assert not result.has_critical_defects
        assert result.score >= 0.8


class TestCritiqueEngineLLM:
    """Test LLM-based critique with mocked LLM."""

    def test_parse_critique_response(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        response = {
            "score": 0.4,
            "summary": "Missing key data",
            "defects": [
                {
                    "category": "missing_data",
                    "location": "root.report",
                    "description": "Report field is empty",
                    "severity": "critical",
                },
                {
                    "category": "wrong_format",
                    "location": "root.data",
                    "description": "Expected array, got string",
                    "severity": "warning",
                },
            ],
            "prescriptions": ["Add report content", "Convert data to array"],
            "reusable_patterns": ["Workers often forget the report field"],
            "effort_estimate": "moderate",
        }

        envelope = engine._parse_critique_response("w1", response)
        assert envelope.score == 0.4
        assert envelope.has_critical_defects
        assert len(envelope.defects) == 2
        assert len(envelope.prescriptions) == 2
        assert envelope.effort_estimate == "moderate"

    def test_parse_string_response(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        response_str = json.dumps(
            {
                "score": 0.9,
                "summary": "Good",
                "defects": [],
                "prescriptions": [],
                "reusable_patterns": [],
                "effort_estimate": "trivial",
            }
        )

        envelope = engine._parse_critique_response("w1", response_str)
        assert envelope.score == 0.9
        assert not envelope.has_critical_defects

    def test_parse_invalid_response(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        envelope = engine._parse_critique_response("w1", "not json at all")
        assert envelope.score == 0.5  # default fallback score


class TestCritiqueEngineRepair:
    """Test the targeted repair mechanism."""

    def test_no_repair_when_no_critical(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        critique = CritiqueEnvelope(
            worker_id="w1",
            score=0.85,
            defects=[Defect("incomplete", "root.x", "minor", "warning")],
        )

        result, attempts = engine.attempt_repair(
            "w1",
            {"confidence": 0.8},
            critique,
            "task",
            {},
            lambda env, t: {"confidence": 0.9},
            lambda: (True, "ok"),
            iteration=1,
        )
        assert len(attempts) == 0
        assert result["confidence"] == 0.8  # unchanged

    def test_repair_improves_result(self, tmp_path: Path):
        cfg = _make_config(enabled=True, max_repair_attempts=2)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        critique = CritiqueEnvelope(
            worker_id="w1",
            score=0.3,
            defects=[Defect("missing_data", "root.x", "no x", "critical")],
            prescriptions=["Add field x"],
        )

        # Mock: repair worker returns better result
        def mock_run_worker(env, task):
            return {"confidence": 0.9, "x": "repaired data"}

        # Mock: re-critique returns clean
        with patch.object(engine, "_run_critique") as mock_critique:
            mock_critique.return_value = CritiqueEnvelope(
                worker_id="w1", score=0.9, summary="Clean after repair"
            )
            result, attempts = engine.attempt_repair(
                "w1",
                {"confidence": 0.3},
                critique,
                "task",
                {},
                mock_run_worker,
                lambda: (True, "ok"),
                iteration=1,
            )

        assert len(attempts) == 1
        assert attempts[0].repaired_score == 0.9
        assert result["confidence"] == 0.9

    def test_repair_stops_on_budget(self, tmp_path: Path):
        cfg = _make_config(enabled=True, max_repair_attempts=3)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        critique = CritiqueEnvelope(
            worker_id="w1",
            score=0.2,
            defects=[Defect("missing_data", "root.x", "no x", "critical")],
        )

        result, attempts = engine.attempt_repair(
            "w1",
            {"confidence": 0.2},
            critique,
            "task",
            {},
            lambda env, t: {"confidence": 0.5},
            lambda: (False, "budget_exhausted"),  # no budget
            iteration=1,
        )
        assert len(attempts) == 0  # could not repair

    def test_repair_stops_when_worse(self, tmp_path: Path):
        cfg = _make_config(enabled=True, max_repair_attempts=3)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        critique = CritiqueEnvelope(
            worker_id="w1",
            score=0.4,
            defects=[Defect("incomplete", "root.x", "half done", "critical")],
        )

        call_count = 0

        def mock_run_worker(env, task):
            nonlocal call_count
            call_count += 1
            return {"confidence": 0.1}  # worse

        with patch.object(engine, "_run_critique") as mock_crit:
            mock_crit.return_value = CritiqueEnvelope(
                worker_id="w1",
                score=0.2,  # worse than before
                defects=[Defect("incomplete", "root.x", "even worse", "critical")],
            )
            result, attempts = engine.attempt_repair(
                "w1",
                {"confidence": 0.4},
                critique,
                "task",
                {},
                mock_run_worker,
                lambda: (True, "ok"),
                iteration=1,
            )

        assert len(attempts) == 1  # stopped after first attempt (got worse)
        assert result["confidence"] == 0.4  # kept original


class TestCritiqueEnginePatterns:
    """Test cross-worker pattern learning."""

    def test_patterns_accumulated(self, tmp_path: Path):
        cfg = _make_config(enabled=True, pattern_memory=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        # Mock _run_critique to return critiques with reusable patterns
        with patch.object(engine, "_run_critique") as mock_crit:
            mock_crit.side_effect = [
                CritiqueEnvelope(
                    worker_id="w1",
                    score=0.5,
                    defects=[Defect("missing_data", "root.x", "no x", "critical")],
                    reusable_patterns=["Workers forget field X"],
                ),
                CritiqueEnvelope(
                    worker_id="w2",
                    score=0.6,
                    defects=[Defect("missing_data", "root.y", "no y", "warning")],
                    reusable_patterns=["Workers forget field X"],
                ),
            ]

            critiques = engine.critique_results(
                [
                    {"worker_id": "w1", "result": {"confidence": 0.5}, "envelope": {}},
                    {"worker_id": "w2", "result": {"confidence": 0.6}, "envelope": {}},
                ],
                task="test task",
                iteration=1,
            )

        assert len(critiques) == 2
        # Pattern should have frequency 2
        patterns = engine.pattern_memory
        assert patterns.has_recurring_pattern("missing_data", min_frequency=2)

    def test_pitfalls_section_generated(self, tmp_path: Path):
        cfg = _make_config(enabled=True, pattern_memory=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        engine._pattern_memory.record("missing_data", "X missing", "Always add X", 1)
        engine._pattern_memory.record("missing_data", "X missing", "Always add X", 2)

        section = engine.build_pattern_pitfalls_section()
        assert "Known Pitfalls" in section
        assert "missing_data" in section
        assert "x2" in section

    def test_manager_summary(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        critiques = [
            CritiqueEnvelope(
                worker_id="w1",
                score=0.9,
                summary="Good",
            ),
            CritiqueEnvelope(
                worker_id="w2",
                score=0.3,
                defects=[Defect("incomplete", "root.x", "half done", "critical")],
                prescriptions=["Complete X"],
            ),
        ]

        summary = engine.get_manager_critique_summary(critiques)
        assert "w1" in summary
        assert "PASS" in summary
        assert "w2" in summary
        assert "NEEDS REPAIR" in summary


class TestBuildRepairPrompt:
    def test_repair_prompt_contains_defects(self, tmp_path: Path):
        cfg = _make_config(enabled=True)
        engine = CritiqueEngine(cfg, tmp_path, "test-run")

        critique = CritiqueEnvelope(
            worker_id="w1",
            score=0.3,
            defects=[
                Defect("missing_data", "root.report", "No report field", "critical"),
                Defect("wrong_format", "root.data", "Wrong type", "warning"),
            ],
            prescriptions=["Add a report field with the analysis text"],
        )

        prompt = engine._build_repair_prompt(
            {"confidence": 0.3},
            critique,
            {"instructions": "Analyze the data"},
        )

        assert "REPAIR MODE" in prompt
        assert "missing_data" in prompt
        assert "No report field" in prompt
        assert "Add a report field" in prompt
