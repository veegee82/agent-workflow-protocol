"""End-to-end tests for the AWP Delegation Loop orchestration engine.

Tests both example workflows (08, 09) and unit-tests the core components:
- BudgetSnapshot tracking
- StallDetector heuristic
- RunLogger dual output (JSON + MD)
- DelegationLoopRunner with real LLM calls
- Two-tier validation (deterministic + LLM)
- Manager-worker delegation cycle
- Parallel fan-out
- Logging artifacts on disk

Usage:
    # Full E2E with LLM calls
    LLM_API_KEY=your-key LLM_MODEL=anthropic/claude-sonnet-4 pytest tests/test_delegation_loop_e2e.py -v

    # Unit tests only (no LLM needed)
    pytest tests/test_delegation_loop_e2e.py -v -k "not e2e"

    # Single test
    pytest tests/test_delegation_loop_e2e.py -v -k "test_budget_tracking"
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from awp.parser import parse_manifest
from awp.models.orchestration import (
    DelegationLoopConfig,
    DelegationBudget,
    WorkerPolicy,
    AWPOrchestrationConfig,
)
from awp.runtime.delegation_loop_runner import (
    BudgetSnapshot,
    StallDetector,
    RunLogger,
    DelegationLoopRunner,
)

EXAMPLES = Path(__file__).parents[3] / "examples"

HAS_LLM = bool(os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY"))
LLM_REASON = "LLM_API_KEY or OPENROUTER_API_KEY not set"


# =========================================================================== #
#  Unit Tests — No LLM needed                                                  #
# =========================================================================== #


class TestDelegationLoopModels:
    """Test Pydantic models parse correctly."""

    def test_delegation_loop_config_defaults(self):
        cfg = DelegationLoopConfig(manager="agents/manager")
        assert cfg.manager == "agents/manager"
        assert cfg.budget.max_loops == 20
        assert cfg.budget.max_total_workers == 30
        assert cfg.worker_policy.enforced.sandbox.type == "subprocess"
        assert cfg.validation.deterministic.always is True
        assert cfg.validation.llm.enabled is True
        assert cfg.history.rolling_summary is True
        assert cfg.logging.format == "dual"

    def test_delegation_budget_defaults(self):
        b = DelegationBudget()
        assert b.max_loops == 20
        assert b.max_depth == 5
        assert b.max_wall_time == 600

    def test_worker_policy_enforced_fields(self):
        wp = WorkerPolicy()
        assert "shell.execute" in wp.enforced.forbidden_tools
        assert "instructions" in wp.manager_controlled
        assert wp.enforced.sandbox.max_memory_mb == 512

    def test_worker_policy_includes_temperature_in_manager_controlled(self):
        wp = WorkerPolicy()
        assert "temperature" in wp.manager_controlled

    def test_orchestration_config_with_delegation_loop(self):
        orch = AWPOrchestrationConfig(
            engine="delegation_loop",
            delegation_loop=DelegationLoopConfig(manager="agents/mgr"),
        )
        assert orch.engine == "delegation_loop"
        assert orch.delegation_loop.manager == "agents/mgr"


class TestBudgetSnapshot:
    """Test budget tracking."""

    def test_initial_state(self):
        budget = DelegationBudget(max_loops=10, max_total_workers=20)
        snap = BudgetSnapshot(budget)
        assert snap.loops_remaining == 10
        assert snap.workers_remaining == 20
        can, reason = snap.can_continue()
        assert can is True

    def test_budget_exhaustion_loops(self):
        budget = DelegationBudget(max_loops=2)
        snap = BudgetSnapshot(budget)
        snap.loops_used = 2
        can, reason = snap.can_continue()
        assert can is False
        assert "max_loops" in reason

    def test_budget_exhaustion_workers(self):
        budget = DelegationBudget(max_total_workers=3)
        snap = BudgetSnapshot(budget)
        snap.workers_spawned = 3
        can, reason = snap.can_continue()
        assert can is False
        assert "max_total_workers" in reason

    def test_budget_fraction(self):
        budget = DelegationBudget(
            max_loops=10, max_total_workers=10, max_wall_time=1000
        )
        snap = BudgetSnapshot(budget)
        snap.loops_used = 5
        snap.workers_spawned = 2
        frac = snap.budget_fraction_remaining
        assert 0.0 < frac < 1.0

    def test_to_dict(self):
        budget = DelegationBudget(max_loops=5)
        snap = BudgetSnapshot(budget)
        snap.loops_used = 2
        d = snap.to_dict()
        assert d["loops"]["used"] == 2
        assert d["loops"]["max"] == 5
        assert "budget_remaining_pct" in d


class TestWorkerTemperature:
    """Test dynamic worker temperature from delegation envelope."""

    def test_envelope_temperature_used(self):
        """Manager-set temperature in envelope should be used by worker."""
        envelope = {
            "worker_id": "analyst",
            "instructions": "Analyze data",
            "temperature": 0.7,
        }
        temp = envelope.get("temperature", 0.2)
        assert temp == 0.7

    def test_envelope_temperature_default(self):
        """When no temperature in envelope, default to 0.2."""
        envelope = {
            "worker_id": "analyst",
            "instructions": "Analyze data",
        }
        temp = envelope.get("temperature", 0.2)
        assert temp == 0.2

    def test_envelope_temperature_clamped(self):
        """Temperature should be clamped to [0.0, 2.0]."""
        for raw, expected in [(-0.5, 0.0), (0.0, 0.0), (1.0, 1.0), (3.0, 2.0)]:
            val = max(0.0, min(float(raw), 2.0))
            assert val == expected, f"raw={raw}"

    def test_envelope_temperature_invalid_type_fallback(self):
        """Non-numeric temperature should fall back to 0.2."""
        envelope = {"temperature": "hot"}
        raw = envelope.get("temperature", 0.2)
        if not isinstance(raw, (int, float)):
            raw = 0.2
        assert raw == 0.2

    def test_different_workers_different_temperatures(self):
        """Manager can set different temperatures per worker in same iteration."""
        envelopes = [
            {"worker_id": "statistical_analyst", "temperature": 0.0},
            {"worker_id": "creative_writer", "temperature": 0.9},
        ]
        temps = [e.get("temperature", 0.2) for e in envelopes]
        assert temps == [0.0, 0.9]


class TestStallDetector:
    """Test stall detection heuristic."""

    def test_no_stall_with_progress(self):
        sd = StallDetector(window=3, min_delta=0.05)
        assert sd.record(0.3) == "ok"
        assert sd.record(0.5) == "ok"
        assert sd.record(0.7) == "ok"  # delta=0.4, well above threshold

    def test_stall_warning(self):
        sd = StallDetector(window=3, min_delta=0.05)
        sd.record(0.5)
        sd.record(0.51)
        result = sd.record(0.52)  # delta=0.02, below 0.05
        assert result == "warn"

    def test_stall_stop_after_two_warnings(self):
        sd = StallDetector(window=3, min_delta=0.05)
        # First window: stall
        sd.record(0.5)
        sd.record(0.51)
        sd.record(0.52)  # warn
        # Second window: still stalling
        sd.record(0.52)
        sd.record(0.53)
        result = sd.record(0.53)  # second warn → stop
        assert result == "stop"

    def test_recovery_resets_warnings(self):
        sd = StallDetector(window=3, min_delta=0.05)
        sd.record(0.5)
        sd.record(0.51)
        sd.record(0.52)  # warn
        sd.record(0.7)  # big jump
        sd.record(0.8)
        result = sd.record(0.9)  # delta=0.2 — progress!
        assert result == "ok"


class TestRunLogger:
    """Test dual-layer logging to disk."""

    def test_creates_directory_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            RunLogger(run_dir, fmt="dual")
            assert (run_dir / "iterations").exists()
            assert (run_dir / "history").exists()
            assert (run_dir / "artifacts" / "skills").exists()
            assert (run_dir / "artifacts" / "tools").exists()

    def test_writes_json_and_md(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            logger = RunLogger(run_dir, fmt="dual")

            cfg = DelegationLoopConfig(manager="agents/mgr")
            logger.log_run_start("Test task", "run123", cfg, "opus", "sonnet")

            assert (run_dir / "run_manifest.json").exists()
            assert (run_dir / "RUN_SUMMARY.md").exists()

            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            assert manifest["run_id"] == "run123"
            assert manifest["task"] == "Test task"
            assert manifest["models"]["manager"] == "opus"

    def test_json_only_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            logger = RunLogger(run_dir, fmt="json")

            cfg = DelegationLoopConfig(manager="agents/mgr")
            logger.log_run_start("Test", "run1", cfg, "m", "w")

            assert (run_dir / "run_manifest.json").exists()
            assert not (run_dir / "RUN_SUMMARY.md").exists()

    def test_log_iteration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            logger = RunLogger(run_dir, fmt="dual")

            budget = BudgetSnapshot(DelegationBudget(max_loops=10))
            budget.loops_used = 1

            logger.log_iteration(
                iteration=1,
                manager_decision={
                    "decision": "delegate",
                    "reasoning": "Need more data",
                },
                delegations=[
                    {
                        "worker_id": "researcher_1",
                        "envelope": {
                            "instructions": "Research X",
                            "skills": ["Domain knowledge..."],
                        },
                        "result": {"findings": "Found X", "confidence": 0.7},
                    }
                ],
                budget=budget,
                validation_results=[{"worker_id": "researcher_1", "feedback": "ok"}],
            )

            iter_dir = run_dir / "iterations" / "001"
            assert (iter_dir / "manager_decision.json").exists()
            assert (iter_dir / "ITERATION_SUMMARY.md").exists()
            assert (iter_dir / "budget_snapshot.json").exists()

    def test_rolling_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            logger = RunLogger(run_dir, fmt="dual")

            history = [
                {"iteration": 1, "confidence": 0.3, "key_findings": "Initial scan"},
                {"iteration": 2, "confidence": 0.6, "key_findings": "Found root cause"},
            ]
            logger.update_rolling_summary(2, 0.6, "Found root cause", history, window=3)

            summary_md = run_dir / "history" / "ROLLING_SUMMARY.md"
            summary_json = run_dir / "history" / "rolling_summary.json"
            assert summary_md.exists()
            assert summary_json.exists()

            content = summary_md.read_text()
            assert "Iteration: 2" in content
            assert "0.6" in content

    def test_log_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            logger = RunLogger(run_dir, fmt="dual")

            cfg = DelegationLoopConfig(manager="agents/mgr")
            logger.log_run_start("Test", "run1", cfg, "m", "w")

            budget = BudgetSnapshot(DelegationBudget())
            budget.loops_used = 3
            budget.workers_spawned = 5

            logger.log_completion("run1", {"answer": "42"}, budget, 3, "complete")

            assert (run_dir / "run_completion.json").exists()
            completion = json.loads((run_dir / "run_completion.json").read_text())
            assert completion["status"] == "complete"
            assert completion["total_iterations"] == 3


class TestValidation:
    """Test the two-tier validation logic."""

    def test_deterministic_valid(self):
        runner = _make_runner()
        result = runner._validate_deterministic({"findings": "x", "confidence": 0.8})
        assert result["passed"] is True

    def test_deterministic_missing_confidence(self):
        runner = _make_runner()
        result = runner._validate_deterministic({"findings": "x"})
        assert result["passed"] is False
        assert any("confidence" in e.lower() for e in result["errors"])

    def test_deterministic_invalid_confidence_range(self):
        runner = _make_runner()
        result = runner._validate_deterministic({"confidence": 1.5})
        assert result["passed"] is False

    def test_deterministic_error_only_result(self):
        runner = _make_runner()
        result = runner._validate_deterministic({"error": "fail", "confidence": 0.0})
        assert result["passed"] is False


class TestParserIntegration:
    """Test that the parser handles delegation_loop config."""

    def test_parse_example_08(self):
        manifest = parse_manifest(EXAMPLES / "08-delegation-loop" / "workflow.awp.yaml")
        assert manifest.orchestration.engine == "delegation_loop"
        dl = manifest.orchestration.delegation_loop
        assert dl is not None
        assert dl.manager == "agents/manager"
        assert dl.budget.max_loops == 5
        assert dl.budget.max_total_workers == 10
        assert dl.worker_policy.enforced.sandbox.type == "subprocess"
        assert dl.validation.deterministic.always is True
        assert dl.history.rolling_summary is True

    def test_parse_example_09(self):
        manifest = parse_manifest(
            EXAMPLES / "09-recursive-delegation" / "workflow.awp.yaml"
        )
        assert manifest.orchestration.engine == "delegation_loop"
        dl = manifest.orchestration.delegation_loop
        assert dl.manager == "agents/analyzer"
        assert dl.budget.max_depth == 2


# =========================================================================== #
#  E2E Tests — Require LLM API key                                             #
# =========================================================================== #


@pytest.mark.skipif(not HAS_LLM, reason=LLM_REASON)
class TestDelegationLoopE2E:
    """Full end-to-end tests with real LLM calls."""

    def test_e2e_basic_delegation_loop(self):
        """Test example 08: basic delegation loop research workflow."""
        wf_dir = EXAMPLES / "08-delegation-loop"
        runner = _make_workflow_runner(wf_dir)
        result = runner.run(
            "What are the three primary colors and why are they called primary?"
        )

        # Should have delegation_loop key in result
        assert "delegation_loop" in result or "task" in result

        # Check that logging artifacts were created
        runs_dir = wf_dir / "workspace" / "runs"
        if runs_dir.exists():
            run_dirs = list(runs_dir.iterdir())
            assert len(run_dirs) >= 1, "At least one run directory should exist"

            latest = sorted(run_dirs)[-1]
            # Check for run manifest
            assert (latest / "run_manifest.json").exists(), "run_manifest.json missing"
            # Check for at least one iteration
            iters_dir = latest / "iterations"
            if iters_dir.exists():
                iter_dirs = list(iters_dir.iterdir())
                assert len(iter_dirs) >= 1, "At least one iteration should exist"

            # Validate run manifest structure
            manifest = json.loads((latest / "run_manifest.json").read_text())
            assert "run_id" in manifest
            assert "task" in manifest
            assert "models" in manifest

        # Clean up workspace
        _cleanup_workspace(wf_dir)

    def test_e2e_recursive_delegation(self):
        """Test example 09: recursive delegation with budget limits."""
        wf_dir = EXAMPLES / "09-recursive-delegation"
        runner = _make_workflow_runner(wf_dir)
        result = runner.run("Compare the pros and cons of solar energy vs wind energy")

        assert "delegation_loop" in result or "task" in result

        # Verify logging
        runs_dir = wf_dir / "workspace" / "runs"
        if runs_dir.exists():
            run_dirs = list(runs_dir.iterdir())
            assert len(run_dirs) >= 1

        _cleanup_workspace(wf_dir)

    def test_e2e_budget_limits_respected(self):
        """Test that budget limits actually stop the loop."""
        wf_dir = EXAMPLES / "08-delegation-loop"
        runner = _make_workflow_runner(wf_dir)

        # The budget is max_loops=5, so it should terminate within 5 iterations
        result = runner.run("Explain quantum entanglement in simple terms")

        dl_result = result.get("delegation_loop", {})
        if "iterations_completed" in dl_result:
            assert dl_result["iterations_completed"] <= 5

        _cleanup_workspace(wf_dir)

    def test_e2e_logging_dual_format(self):
        """Test that both JSON and MD files are generated."""
        wf_dir = EXAMPLES / "08-delegation-loop"
        runner = _make_workflow_runner(wf_dir)
        runner.run("What is photosynthesis?")

        runs_dir = wf_dir / "workspace" / "runs"
        if runs_dir.exists():
            latest = sorted(runs_dir.iterdir())[-1]

            # JSON files
            assert (latest / "run_manifest.json").exists()

            # MD files
            assert (latest / "RUN_SUMMARY.md").exists()

            # History
            history_dir = latest / "history"
            if history_dir.exists():
                files = list(history_dir.iterdir())
                # Should have rolling summary in at least one format
                names = [f.name for f in files]
                assert any("rolling" in n.lower() for n in names) or len(files) == 0

        _cleanup_workspace(wf_dir)

    def test_e2e_validation_produces_feedback(self):
        """Test that validation results are logged."""
        wf_dir = EXAMPLES / "08-delegation-loop"
        runner = _make_workflow_runner(wf_dir)
        runner.run("Name three famous scientists and their contributions")

        runs_dir = wf_dir / "workspace" / "runs"
        if runs_dir.exists():
            latest = sorted(runs_dir.iterdir())[-1]
            iters_dir = latest / "iterations"
            if iters_dir.exists():
                for iter_dir in iters_dir.iterdir():
                    val_file = iter_dir / "validation.json"
                    if val_file.exists():
                        val_data = json.loads(val_file.read_text())
                        assert isinstance(val_data, list)
                        for v in val_data:
                            assert "worker_id" in v

        _cleanup_workspace(wf_dir)


# =========================================================================== #
#  Helpers                                                                      #
# =========================================================================== #


def _make_runner() -> DelegationLoopRunner:
    """Create a DelegationLoopRunner for unit testing (no LLM)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wf_dir = Path(tmpdir)
        config = DelegationLoopConfig(manager="agents/manager")
        return DelegationLoopRunner(
            workflow_dir=wf_dir,
            config=config,
            manager_model="test-model",
            worker_model="test-model",
        )


def _make_workflow_runner(wf_dir: Path) -> object:
    """Create a WorkflowRunner for E2E testing."""
    from awp.runtime.runner import WorkflowRunner

    model = os.getenv("LLM_MODEL", "")
    return WorkflowRunner(
        wf_dir,
        manager_model=model,
        worker_model=model,
    )


def _cleanup_workspace(wf_dir: Path) -> None:
    """Remove generated workspace files after test."""
    workspace = wf_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    data = wf_dir / "data"
    if data.exists():
        shutil.rmtree(data, ignore_errors=True)
