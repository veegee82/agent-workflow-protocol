"""End-to-end integration test for the Reflective Critique Loop.

Tests the full pipeline: delegation loop → worker execution → critique →
targeted repair → pattern accumulation, using a mocked LLM so no API key
is needed.
"""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from awp.models.orchestration import (
    CritiqueConfig,
    DelegationBudget,
    DelegationLoopConfig,
    DelegationLoopModels,
    DelegationLoggingConfig,
    HistoryConfig,
    StallDetectionConfig,
    ValidationConfig,
    WorkerPolicy,
)
from awp.runtime.delegation_loop_runner import DelegationLoopRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_llm_responses() -> list[dict]:
    """Sequence of LLM responses simulating a 2-iteration run.

    Iteration 1: Manager delegates 2 workers.
      - Worker A: produces good result → critic scores 0.9
      - Worker B: produces incomplete result → critic scores 0.3 (critical)
        → repair attempt → critic re-scores 0.85

    Iteration 2: Manager completes with final result.
    """
    return [
        # --- Iteration 1: Manager delegates ---
        {
            "decision": "delegate",
            "reasoning": "Breaking task into analysis and summary",
            "confidence": 0.3,
            "delegations": [
                {
                    "worker_id": "analyzer",
                    "instructions": "Analyze the input data and produce a report",
                    "tools_allowed": [],
                    "output_contract": {
                        "required_fields": ["analysis", "confidence"],
                    },
                    "temperature": 0.2,
                },
                {
                    "worker_id": "summarizer",
                    "instructions": "Summarize the findings",
                    "tools_allowed": [],
                    "output_contract": {
                        "required_fields": ["summary", "confidence"],
                    },
                    "temperature": 0.2,
                },
            ],
        },
        # --- Worker A (analyzer): good result ---
        {
            "analyzer": {
                "analysis": "Detailed analysis of the data showing trends X, Y, Z",
                "confidence": 0.85,
            }
        },
        # --- Critic for Worker A: high score ---
        {
            "score": 0.9,
            "summary": "Good analysis with sufficient detail",
            "defects": [],
            "prescriptions": [],
            "reusable_patterns": [],
            "effort_estimate": "trivial",
        },
        # --- Worker B (summarizer): incomplete result ---
        {
            "summarizer": {
                "confidence": 0.4,
                # Missing "summary" field → will trigger critique
            }
        },
        # --- Critic for Worker B: low score with critical defect ---
        {
            "score": 0.3,
            "summary": "Missing required 'summary' field",
            "defects": [
                {
                    "category": "missing_data",
                    "location": "root.summary",
                    "description": "Required field 'summary' is absent from output",
                    "severity": "critical",
                }
            ],
            "prescriptions": ["Add a 'summary' field with the summarized findings"],
            "reusable_patterns": ["Workers often omit required output fields"],
            "effort_estimate": "trivial",
        },
        # --- Repair worker for B: fixed result ---
        {
            "summarizer_repair": {
                "summary": "Data shows trends X, Y, Z with strong correlation",
                "confidence": 0.8,
            }
        },
        # --- Critic re-scores repaired Worker B: good now ---
        {
            "score": 0.85,
            "summary": "Repaired output now includes summary",
            "defects": [],
            "prescriptions": [],
            "reusable_patterns": [],
            "effort_estimate": "trivial",
        },
        # --- Iteration 2: Manager completes ---
        {
            "decision": "complete",
            "reasoning": "Both workers produced quality results after critique/repair",
            "confidence": 0.85,
            "final_result": {
                "analysis": "Trends X, Y, Z identified",
                "summary": "Strong correlation found",
                "confidence": 0.85,
            },
        },
    ]


class _MockLLMClient:
    """Mock LLM that returns pre-configured responses in sequence."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self._call_index = 0
        self.total_tokens_used = 0

    def chat_json(self, messages: list, **kwargs: Any) -> dict:
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            self.total_tokens_used += 100
            return resp
        return {"decision": "complete", "final_result": {"confidence": 0.5}, "confidence": 0.5}

    def chat(self, messages: list, **kwargs: Any) -> dict:
        resp = self.chat_json(messages, **kwargs)
        return {"choices": [{"message": {"content": json.dumps(resp)}}]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCritiqueE2E:
    """End-to-end tests for the Reflective Critique Loop integration."""

    def _make_config(
        self,
        critique_enabled: bool = True,
        max_repair_attempts: int = 2,
        pattern_memory: bool = True,
    ) -> DelegationLoopConfig:
        return DelegationLoopConfig(
            manager="agents/manager",
            models=DelegationLoopModels(manager="mock", worker="mock"),
            budget=DelegationBudget(
                max_loops=4,
                max_total_workers=10,
                max_total_tokens=50000,
                max_wall_time=120,
                max_tool_calls=20,
            ),
            termination=StallDetectionConfig(enabled=False),
            validation=ValidationConfig(),
            history=HistoryConfig(full_results_window=3),
            logging=DelegationLoggingConfig(format="dual"),
            critique=CritiqueConfig(
                enabled=critique_enabled,
                mode="inline",
                max_repair_attempts=max_repair_attempts,
                repair_budget_fraction=0.20,
                pattern_memory=pattern_memory,
            ),
        )

    def test_critique_disabled_passthrough(self, tmp_path: Path):
        """When critique is disabled, the loop works as before."""
        config = self._make_config(critique_enabled=False)
        responses = [
            # Manager delegates
            {
                "decision": "delegate",
                "delegations": [
                    {"worker_id": "w1", "instructions": "Do stuff", "tools_allowed": []},
                ],
                "confidence": 0.3,
            },
            # Worker result
            {"w1": {"data": "result", "confidence": 0.7}},
            # Manager completes
            {
                "decision": "complete",
                "final_result": {"data": "done", "confidence": 0.8},
                "confidence": 0.8,
            },
        ]

        mock_llm = _MockLLMClient(responses)
        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
            llm_client=mock_llm,
        )

        # Create minimal workspace
        (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)

        with (
            patch.object(runner, "_run_inline_manager") as mock_mgr,
            patch.object(runner, "_run_ephemeral_worker") as mock_worker,
        ):
            mock_mgr.side_effect = [responses[0], responses[2]]
            mock_worker.return_value = {"data": "result", "confidence": 0.7}

            result = runner.run("Test task")

        assert "delegation_loop" in result
        # No critique data should be present
        assert runner._critique_engine is None

    def test_critique_engine_initialized(self, tmp_path: Path):
        """Critique engine is initialized when config.critique.enabled=True."""
        config = self._make_config(critique_enabled=True)

        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
        )

        assert runner._critique_engine is not None
        assert runner._critique_engine.enabled

    def test_critique_logged_to_disk(self, tmp_path: Path):
        """Critique results are persisted to the run directory."""
        config = self._make_config(critique_enabled=True)

        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
        )

        # Create workspace
        (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)

        # Simulate a full run with mocked methods
        delegation_results = [
            {
                "worker_id": "w1",
                "envelope": {
                    "instructions": "Do X",
                    "output_contract": {"required_fields": ["data"]},
                },
                "result": {"data": "result", "confidence": 0.8},
                "status": "ok",
            },
        ]

        critiques = runner._critique_engine.critique_results(
            delegation_results, "Test task", iteration=1
        )

        # Log to disk
        runner._logger.log_critique(
            1,
            [c.to_dict() for c in critiques],
            runner._critique_engine.get_summary(),
        )

        # Verify files exist
        run_dir = runner._logger.run_dir
        iter_dir = run_dir / "iterations" / "001"
        assert (iter_dir / "critique.json").exists()
        assert (iter_dir / "CRITIQUE.md").exists()

        # Verify content
        critique_data = json.loads((iter_dir / "critique.json").read_text())
        assert "critiques" in critique_data
        assert "summary" in critique_data

        md_content = (iter_dir / "CRITIQUE.md").read_text()
        assert "Critique" in md_content
        assert "w1" in md_content

    def test_pattern_memory_persists_across_iterations(self, tmp_path: Path):
        """Patterns from iteration 1 are available to iteration 2 workers."""
        config = self._make_config(critique_enabled=True, pattern_memory=True)

        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
        )

        engine = runner._critique_engine

        # Simulate pattern from iteration 1
        engine._pattern_memory.record(
            "missing_data",
            "Workers forget confidence field",
            "Always include a 'confidence' field in output",
            iteration=1,
        )

        # Build pitfalls section for iteration 2 workers
        pitfalls = engine.build_pattern_pitfalls_section()
        assert "Known Pitfalls" in pitfalls
        assert "missing_data" in pitfalls
        assert "confidence" in pitfalls

    def test_heuristic_critique_detects_missing_fields(self, tmp_path: Path):
        """Heuristic fallback catches missing required fields."""
        config = self._make_config(critique_enabled=True)

        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
        )

        engine = runner._critique_engine

        # Worker result missing required field
        critique = engine._heuristic_critique(
            "test_worker",
            {"confidence": 0.6},  # missing "report" field
            {"output_contract": {"required_fields": ["report", "confidence"]}},
        )

        assert critique.has_critical_defects
        assert any(
            d.category == "missing_data" and "report" in d.description for d in critique.defects
        )

    def test_repair_history_tracked(self, tmp_path: Path):
        """Repair attempts are recorded in engine history."""
        config = self._make_config(critique_enabled=True, max_repair_attempts=1)
        engine_module = "awp.runtime.critique.engine"

        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
        )

        engine = runner._critique_engine
        from awp.runtime.critique.models import CritiqueEnvelope, Defect

        critique = CritiqueEnvelope(
            worker_id="w1",
            score=0.3,
            defects=[Defect("missing_data", "root.x", "no x", "critical")],
            prescriptions=["Add field x"],
        )

        # Mock repair: worker returns fixed result, re-critique is clean
        with patch.object(engine, "_run_critique") as mock_crit:
            mock_crit.return_value = CritiqueEnvelope(worker_id="w1", score=0.9, summary="Fixed")

            result, attempts = engine.attempt_repair(
                "w1",
                {"confidence": 0.3},
                critique,
                "task",
                {},
                lambda env, task: {"confidence": 0.9, "x": "data"},
                lambda: (True, "ok"),
                iteration=1,
            )

        assert len(attempts) == 1
        assert engine.repair_history[0].repaired_score == 0.9

        # Summary includes repair
        summary = engine.get_summary()
        assert len(summary["repair_history"]) == 1

    def test_manager_receives_critique_summary(self, tmp_path: Path):
        """Manager task context includes critique feedback from previous iteration."""
        config = self._make_config(critique_enabled=True)

        runner = DelegationLoopRunner(
            workflow_dir=tmp_path,
            config=config,
            manager_model="mock",
            worker_model="mock",
        )

        # Simulate history with critique
        from awp.runtime.critique.models import CritiqueEnvelope, Defect

        critiques = [
            CritiqueEnvelope(
                worker_id="w1",
                score=0.4,
                defects=[Defect("incomplete", "root.x", "half done", "critical")],
                prescriptions=["Complete X"],
            ),
        ]
        critique_summary = runner._critique_engine.get_manager_critique_summary(critiques)

        runner._history.append(
            {
                "iteration": 1,
                "confidence": 0.5,
                "key_findings": "Partial results",
                "worker_count": 1,
                "validation": [],
                "critique_summary": critique_summary,
            }
        )

        # Build manager task for iteration 2
        task_prompt = runner._build_manager_task("Test task", {"task": "Test"}, 2)

        assert "Critique Summary" in task_prompt
        assert "NEEDS REPAIR" in task_prompt
        assert "w1" in task_prompt
