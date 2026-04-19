"""Verify AgentWorkflow threads parent_run_id and tags into run_completion.json."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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


def test_delegation_loop_runner_writes_parent_run_id_into_completion(
    tmp_path: Path,
) -> None:
    """Stub-level test: DelegationLoopRunner persists parent_run_id + tags."""
    from awp.models.orchestration import (
        DelegationBudget,
        DelegationLoopConfig,
        DelegationLoopModels,
        WorkerPolicy,
        WorkerPolicyEnforced,
    )
    from awp.runtime.delegation_loop_runner import DelegationLoopRunner
    from awp.runtime.tools import ToolRegistry

    (tmp_path / "agents" / "manager").mkdir(parents=True)
    (tmp_path / "agents" / "manager" / "system_prompt.md").write_text(
        "stub", encoding="utf-8"
    )

    cfg = DelegationLoopConfig(
        manager="agents/manager",
        models=DelegationLoopModels(
            manager="openai/gpt-5-mini", worker="openai/gpt-5-mini"
        ),
        budget=DelegationBudget(
            max_loops=1,
            max_total_workers=1,
            max_total_tokens=100,
            max_wall_time=5,
            max_tool_calls=1,
            max_depth=1,
        ),
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
    # Stub the actual loop — return (final_result, status).
    with patch.object(
        runner, "_loop", return_value=({"confidence": 0.5}, "complete")
    ):
        runner.run("trivial")

    run_completion_path = next(tmp_path.rglob("run_completion.json"), None)
    assert run_completion_path is not None, "run_completion.json must be written"
    data = json.loads(run_completion_path.read_text(encoding="utf-8"))
    assert data.get("parent_run_id") == "run_seed_123"
    assert data.get("tags") == ["refinement", "refine-iter-1"]
