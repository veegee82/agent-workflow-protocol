"""End-to-end tests for experiment context injection into new runs.

Verifies that when a new run starts inside an existing experiment,
the manager receives previous run results (prompt injection) and
workspace state files (_experiment_context/).

Note: _build_experiment_context() creates its own event loop (designed
for background threads), so tests that call it must do so from a real
thread — not from an already-running async loop.
"""

from __future__ import annotations

import asyncio
import json
import concurrent.futures
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from server.services.store import StoreService


# ---------------------------------------------------------------------------
# Helper: populate a test DB with a 3-run experiment (sync, own loop)
# ---------------------------------------------------------------------------


def _populate_experiment_db(db_path: Path) -> None:
    """Create and populate a test SQLite DB synchronously."""

    async def _setup():
        store = StoreService(db_path=db_path)
        await store.init_db()

        session_id = "exp-revenue-2026"
        await store.create_session(
            session_id=session_id,
            title="Revenue Analysis Q1-Q4",
            description="Investigate revenue trends across all quarters",
            hypothesis="Revenue dip in Q3 is caused by supply chain disruptions",
            tags=["revenue", "supply-chain", "2026"],
        )

        # Run 1: Initial revenue analysis
        await store.save_run(
            run_id="run_001",
            task="Analyze quarterly revenue data and identify trends",
            model="openrouter/anthropic/claude-sonnet-4",
            config={"task": "Analyze quarterly revenue data", "model": "test"},
            status="complete",
        )
        await store.update_run(
            run_id="run_001",
            status="complete",
            result={
                "status": "complete",
                "result": {
                    "delegation_loop": {
                        "answer": "Q1: $2.1M, Q2: $2.3M, Q3: $1.8M (dip), Q4: $2.5M. "
                        "YoY growth: 12%. Q3 shows a 22% drop from Q2.",
                        "confidence": 0.87,
                    }
                },
            },
            completed_at="2026-03-25T10:00:00Z",
        )
        await store.add_run_to_session(session_id, "run_001")

        # Run 2: Deep dive into Q3
        await store.save_run(
            run_id="run_002",
            task="Deep-dive into Q3 revenue dip — correlate with supply chain data",
            model="openrouter/anthropic/claude-sonnet-4",
            config={"task": "Deep-dive Q3 dip", "model": "test"},
            status="complete",
        )
        await store.update_run(
            run_id="run_002",
            status="complete",
            result={
                "status": "complete",
                "result": {
                    "delegation_loop": {
                        "answer": "Supply chain disruption in July caused 3-week shipping delay. "
                        "Correlation between shipping delays and revenue: r=0.73. "
                        "Affected product lines: Electronics (40% drop), Home (15% drop).",
                        "confidence": 0.91,
                    }
                },
            },
            completed_at="2026-03-27T14:30:00Z",
        )
        await store.add_run_to_session(session_id, "run_002")

        # Run 3: Forecast with mitigation
        await store.save_run(
            run_id="run_003",
            task="Build Q3 2027 forecast assuming supply chain mitigation is in place",
            model="openrouter/anthropic/claude-sonnet-4",
            config={"task": "Build Q3 forecast", "model": "test"},
            status="complete",
        )
        await store.update_run(
            run_id="run_003",
            status="complete",
            result={
                "status": "complete",
                "result": {
                    "delegation_loop": {
                        "answer": "With dual-supplier strategy: projected Q3 2027 revenue $2.2M "
                        "(vs $1.8M in 2026). Confidence interval: $2.0M-$2.4M.",
                        "confidence": 0.78,
                    }
                },
            },
            completed_at="2026-03-29T09:15:00Z",
        )
        await store.add_run_to_session(session_id, "run_003")

        # Memory entries
        await store.save_memory_entry(
            session_id=session_id,
            content="Revenue correlation with shipping delays: r=0.73",
            entry_type="finding",
            source="agent",
            run_id="run_002",
        )
        await store.save_memory_entry(
            session_id=session_id,
            content="Focus next analysis on logistics data and dual-supplier ROI",
            entry_type="decision",
            source="user",
        )
        await store.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup())
    finally:
        loop.close()


def _populate_many_runs_db(db_path: Path) -> None:
    """Create a DB with 8 runs for truncation testing."""

    async def _setup():
        store = StoreService(db_path=db_path)
        await store.init_db()
        session_id = "exp-many-runs"
        await store.create_session(session_id=session_id, title="Many Runs")

        for i in range(1, 9):
            run_id = f"run_{i:03d}"
            await store.save_run(
                run_id=run_id,
                task=f"Task number {i}: Analyze segment {i}",
                model="test-model",
                config={"task": f"Task {i}", "model": "test"},
                status="complete",
            )
            await store.update_run(
                run_id=run_id,
                status="complete",
                result={
                    "status": "complete",
                    "result": {
                        "delegation_loop": {
                            "answer": f"Result for task {i}: Found {i * 10}% growth in segment {i}.",
                            "confidence": 0.5 + i * 0.05,
                        }
                    },
                },
                completed_at=f"2026-03-{i:02d}T10:00:00Z",
            )
            await store.add_run_to_session(session_id, run_id)
        await store.close()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_setup())
    finally:
        loop.close()


def _run_in_thread(fn, *args):
    """Run a function in a separate thread (simulates background runner)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args)
        return future.result(timeout=10)


# ---------------------------------------------------------------------------
# Test: _build_experiment_context returns correct prompt + state files
# ---------------------------------------------------------------------------


def test_build_experiment_context_prompt(tmp_path, monkeypatch):
    """Verify the prompt context string contains all 3 runs and memory."""
    db_path = tmp_path / "test.db"
    _populate_experiment_db(db_path)

    _original_init = StoreService.__init__

    def _patched_init(self, db_path_arg=None):
        _original_init(self, db_path=db_path)

    monkeypatch.setattr(StoreService, "__init__", _patched_init)

    from server.services.runner_service import _build_experiment_context

    # Must run in a thread (no running event loop)
    prompt_ctx, state_files = _run_in_thread(
        _build_experiment_context, "exp-revenue-2026"
    )

    # --- Verify prompt context (Approach 1) ---
    assert "## Experiment Context" in prompt_ctx
    assert "Revenue Analysis Q1-Q4" in prompt_ctx
    assert "supply chain disruptions" in prompt_ctx  # hypothesis

    # All 3 run tasks should appear
    assert "Analyze quarterly revenue data" in prompt_ctx
    assert "Deep-dive into Q3 revenue dip" in prompt_ctx
    assert "Build Q3 2027 forecast" in prompt_ctx

    # Results should be present
    assert "Q3 shows a 22% drop" in prompt_ctx
    assert "r=0.73" in prompt_ctx  # from run 2 result AND memory

    # Memory entries
    assert "[finding]" in prompt_ctx
    assert "[decision]" in prompt_ctx
    assert "dual-supplier ROI" in prompt_ctx

    # Continuation instructions
    assert "continuing an existing experiment" in prompt_ctx
    assert "_experiment_context/" in prompt_ctx


def test_build_experiment_context_state_files(tmp_path, monkeypatch):
    """Verify the state files dict has complete, untruncated data."""
    db_path = tmp_path / "test.db"
    _populate_experiment_db(db_path)

    _original_init = StoreService.__init__

    def _patched_init(self, db_path_arg=None):
        _original_init(self, db_path=db_path)

    monkeypatch.setattr(StoreService, "__init__", _patched_init)

    from server.services.runner_service import _build_experiment_context

    _, state_files = _run_in_thread(
        _build_experiment_context, "exp-revenue-2026"
    )

    # experiment.json
    exp = state_files["experiment.json"]
    assert exp["title"] == "Revenue Analysis Q1-Q4"
    assert exp["hypothesis"] == "Revenue dip in Q3 is caused by supply chain disruptions"
    assert "revenue" in exp["tags"]

    # runs
    runs = state_files["runs"]
    assert len(runs) == 3
    assert runs[0]["run_number"] == 1
    assert "quarterly revenue" in runs[0]["task"]
    assert runs[1]["run_number"] == 2
    assert runs[2]["run_number"] == 3

    # memory.json
    memory = state_files["memory.json"]
    assert len(memory) == 2
    assert any(m["type"] == "finding" for m in memory)
    assert any(m["type"] == "decision" for m in memory)

    # brief markdown
    brief = state_files["experiment_brief.md"]
    assert "Revenue Analysis Q1-Q4" in brief
    assert "Run 1:" in brief
    assert "Run 2:" in brief
    assert "Run 3:" in brief


# ---------------------------------------------------------------------------
# Test: _write_experiment_state_files creates actual files
# ---------------------------------------------------------------------------


def test_write_experiment_state_files(tmp_path, monkeypatch):
    """Verify files are written to workspace/_experiment_context/."""
    db_path = tmp_path / "test.db"
    _populate_experiment_db(db_path)

    _original_init = StoreService.__init__

    def _patched_init(self, db_path_arg=None):
        _original_init(self, db_path=db_path)

    monkeypatch.setattr(StoreService, "__init__", _patched_init)

    from server.services.runner_service import (
        _build_experiment_context,
        _write_experiment_state_files,
    )

    _, state_files = _run_in_thread(
        _build_experiment_context, "exp-revenue-2026"
    )

    workspace = tmp_path / "workspace_test"
    _write_experiment_state_files(workspace, state_files)

    ctx_dir = workspace / "workspace" / "_experiment_context"
    assert ctx_dir.exists()

    # experiment.json
    exp_file = ctx_dir / "experiment.json"
    assert exp_file.exists()
    exp_data = json.loads(exp_file.read_text())
    assert exp_data["title"] == "Revenue Analysis Q1-Q4"

    # Per-run summaries
    assert (ctx_dir / "run_001_summary.json").exists()
    assert (ctx_dir / "run_002_summary.json").exists()
    assert (ctx_dir / "run_003_summary.json").exists()

    run2 = json.loads((ctx_dir / "run_002_summary.json").read_text())
    assert "Deep-dive" in run2["task"]
    assert "r=0.73" in run2["result"]

    # memory.json
    mem_file = ctx_dir / "memory.json"
    assert mem_file.exists()
    mem_data = json.loads(mem_file.read_text())
    assert len(mem_data) == 2

    # experiment_brief.md
    brief_file = ctx_dir / "experiment_brief.md"
    assert brief_file.exists()
    brief = brief_file.read_text()
    assert "Run 1:" in brief
    assert "dual-supplier" in brief


# ---------------------------------------------------------------------------
# Test: Empty session returns empty context (no crash)
# ---------------------------------------------------------------------------


def test_empty_session_returns_empty_context(tmp_path, monkeypatch):
    """A session with no runs should produce empty context, not crash."""
    db_path = tmp_path / "empty_test.db"

    async def _setup():
        store = StoreService(db_path=db_path)
        await store.init_db()
        await store.create_session(session_id="empty-exp", title="Empty Experiment")
        await store.close()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup())
    loop.close()

    _original_init = StoreService.__init__

    def _patched_init(self, db_path_arg=None):
        _original_init(self, db_path=db_path)

    monkeypatch.setattr(StoreService, "__init__", _patched_init)

    from server.services.runner_service import _build_experiment_context

    prompt_ctx, state_files = _run_in_thread(
        _build_experiment_context, "empty-exp"
    )

    assert "Empty Experiment" in prompt_ctx
    assert state_files["runs"] == []
    assert state_files["memory.json"] == []


# ---------------------------------------------------------------------------
# Test: Nonexistent session returns empty strings
# ---------------------------------------------------------------------------


def test_nonexistent_session_returns_empty(tmp_path, monkeypatch):
    """A missing session_id should return empty, not raise."""
    db_path = tmp_path / "missing_test.db"

    async def _setup():
        store = StoreService(db_path=db_path)
        await store.init_db()
        await store.close()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_setup())
    loop.close()

    _original_init = StoreService.__init__

    def _patched_init(self, db_path_arg=None):
        _original_init(self, db_path=db_path)

    monkeypatch.setattr(StoreService, "__init__", _patched_init)

    from server.services.runner_service import _build_experiment_context

    prompt_ctx, state_files = _run_in_thread(
        _build_experiment_context, "does-not-exist"
    )

    assert prompt_ctx == ""
    assert state_files == {}


# ---------------------------------------------------------------------------
# Test: Smart truncation for many runs (>5 recent)
# ---------------------------------------------------------------------------


def test_truncation_for_many_runs(tmp_path, monkeypatch):
    """With 8 runs and _FULL_DETAIL_RUNS=10, all 8 should have full results."""
    db_path = tmp_path / "many_runs.db"
    _populate_many_runs_db(db_path)

    _original_init = StoreService.__init__

    def _patched_init(self, db_path_arg=None):
        _original_init(self, db_path=db_path)

    monkeypatch.setattr(StoreService, "__init__", _patched_init)

    from server.services.runner_service import _build_experiment_context

    prompt_ctx, state_files = _run_in_thread(
        _build_experiment_context, "exp-many-runs"
    )

    # All 8 runs should be in state files (untruncated)
    assert len(state_files["runs"]) == 8

    # All 8 runs fit within _FULL_DETAIL_RUNS=10, so all should have
    # full "Result:" blocks in the prompt (no "Earlier Runs" section).
    for i in range(1, 9):
        assert f"Result for task {i}" in prompt_ctx

    # No truncation to "Earlier Runs" since 8 < 10
    assert "Earlier Runs" not in prompt_ctx


# ---------------------------------------------------------------------------
# Test: AgentWorkflow accepts experiment_context param
# ---------------------------------------------------------------------------


def _load_workflow_class():
    """Import AgentWorkflow from packages/awp-runtime (not reference/)."""
    import importlib.util
    import sys

    wf_path = (
        Path(__file__).resolve().parents[2]
        / "awp-runtime"
        / "src"
        / "awp"
        / "data"
        / "workflow.py"
    )
    spec = importlib.util.spec_from_file_location("awp_runtime_workflow", wf_path)
    mod = importlib.util.module_from_spec(spec)
    # Temporarily ensure awp.data namespace resolves correctly
    spec.loader.exec_module(mod)
    return mod.AgentWorkflow


def test_agent_workflow_accepts_experiment_context():
    """AgentWorkflow.__init__ should accept experiment_context without error."""
    AgentWorkflow = _load_workflow_class()

    wf = AgentWorkflow(
        inputs={},
        task="Test task",
        model="test-model",
        experiment_context="## Previous results\nRun 1 found X.",
    )
    assert wf.experiment_context == "## Previous results\nRun 1 found X."


def test_agent_workflow_experiment_context_defaults_none():
    """Without experiment_context, it should default to None."""
    AgentWorkflow = _load_workflow_class()

    wf = AgentWorkflow(inputs={}, task="Test", model="test-model")
    assert wf.experiment_context is None


# ---------------------------------------------------------------------------
# Test: _extract_result_answer handles partial results
# ---------------------------------------------------------------------------


def test_extract_result_answer_partial():
    """Partial results should produce a structured summary, not raw dict."""
    from server.services.store import _extract_result_answer

    result = {
        "status": "partial",
        "result": {
            "partial": True,
            "termination_reason": "forced_convergence",
            "iterations_completed": 6,
            "confidence": 0.9,
        },
        "output_files": ["chart.png", "data.csv"],
    }
    answer = _extract_result_answer(result)
    assert "[Run ended with status: partial]" in answer
    assert "forced_convergence" in answer
    assert "Iterations completed: 6" in answer
    assert "confidence: 0.9" in answer or "Final confidence: 0.9" in answer
    assert "chart.png" in answer


def test_extract_result_answer_complete():
    """Complete results with an answer should still work."""
    from server.services.store import _extract_result_answer

    result = {
        "status": "complete",
        "result": {"delegation_loop": {"answer": "The answer is 42"}},
    }
    assert _extract_result_answer(result) == "The answer is 42"


# ---------------------------------------------------------------------------
# Test: Interrupted runs produce summaries from events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interrupted_run_summary(tmp_path):
    """Interrupted runs should extract worker results from events."""
    store = StoreService(db_path=tmp_path / "test.db")
    await store.init_db()

    session_id = "exp-interrupted"
    await store.create_session(session_id=session_id, title="Interrupted Test")

    # Create a run that was interrupted
    await store.save_run(
        run_id="int_run_1",
        task="Analyze data",
        model="test",
        config={},
        status="interrupted",
    )
    await store.add_run_to_session(session_id, "int_run_1")

    # Add some events including a worker.complete
    await store.save_event(
        run_id="int_run_1",
        seq=1,
        event_type="run.start",
        data={"task": "Analyze data"},
    )
    await store.save_event(
        run_id="int_run_1",
        seq=2,
        event_type="iteration.start",
        data={"iteration": 1},
    )
    await store.save_event(
        run_id="int_run_1",
        seq=3,
        event_type="worker.spawn",
        data={"worker_id": "data_worker"},
    )
    await store.save_event(
        run_id="int_run_1",
        seq=4,
        event_type="worker.complete",
        data={
            "worker_id": "data_worker",
            "confidence": 0.85,
            "result": "Found 1234 rows with 5% missing values",
        },
    )

    history = await store.get_session_history(session_id)

    # Should have user + assistant pair
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"

    # The assistant content should contain the salvaged worker result
    content = history[1]["content"]
    assert "[Run was interrupted before completing]" in content
    assert "data_worker" in content
    assert "1234 rows" in content
    assert "1 iterations" in content
    assert "1 workers spawned" in content

    await store.close()


@pytest.mark.asyncio
async def test_interrupted_run_no_events(tmp_path):
    """Interrupted runs with no events should still produce a useful message."""
    store = StoreService(db_path=tmp_path / "test.db")
    await store.init_db()

    session_id = "exp-empty-int"
    await store.create_session(session_id=session_id, title="Empty Interrupted")

    await store.save_run(
        run_id="empty_int_1",
        task="Do something",
        model="test",
        config={},
        status="interrupted",
    )
    await store.add_run_to_session(session_id, "empty_int_1")

    history = await store.get_session_history(session_id)
    content = history[1]["content"]
    assert "[Run was interrupted before completing]" in content

    await store.close()
