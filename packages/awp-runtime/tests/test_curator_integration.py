"""Integration tests for Baustein 4 curator + runner priming.

These tests DO NOT call any LLM. They construct a
:class:`DelegationLoopRunner` in memory, seed ``<workflow_dir>/memory/``
via a direct :class:`Curator` run, and then assert that
``_build_manager_task`` injects the ``PRIOR RUN MEMORY`` block on the
first root iteration and omits it on subsequent iterations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.models.orchestration import DelegationLoopConfig
from awp.runtime.curator import Curator
from awp.runtime.delegation_loop_runner import DelegationLoopRunner


def _make_runner(workflow_dir: Path, auto_curation: bool = True) -> DelegationLoopRunner:
    cfg = DelegationLoopConfig()
    cfg.auto_curation_enabled = auto_curation
    # Disable blackboard + digest writes to keep the construction light.
    cfg.blackboard_enabled = False
    cfg.digest_enabled = False
    runner = DelegationLoopRunner(
        workflow_dir=workflow_dir,
        config=cfg,
        tool_registry=None,
        manager_model=None,
        worker_model=None,
        run_id="run2",
    )
    return runner


def _seed_memory(workflow_dir: Path) -> None:
    """Write prior memory exactly as the Curator would after run 1."""
    class _Reg:
        _dynamic_tools = {"dynamic.seed_tool": {"creator": "worker_seed"}}
        _definitions = {
            "dynamic.seed_tool": {
                "function": {
                    "description": "Seed tool from prior run.",
                    "parameters": {"type": "object"},
                }
            }
        }
    Curator(
        workflow_dir=workflow_dir,
        run_id="run1",
        digest_store=None,
        final_result={},
        dynamic_tools_registry=_Reg(),
        root_digest_sha=None,
        failed_signatures=[
            {"signature": "sigX", "reason": "redundant", "iteration": 2, "instructions": "do bad X"}
        ],
    ).curate()


def test_prior_memory_injected_on_first_root_iteration(tmp_path):
    wf = tmp_path / "wf"
    wf.mkdir()
    _seed_memory(wf)

    runner = _make_runner(wf, auto_curation=True)
    first = runner._build_manager_task("some task", {}, iteration=1)
    later = runner._build_manager_task("some task", {}, iteration=2)

    assert "PRIOR RUN MEMORY" in first
    assert "seed_tool" in first
    assert "PRIOR RUN MEMORY" not in later


def test_prior_memory_disabled_when_auto_curation_off(tmp_path):
    wf = tmp_path / "wf"
    wf.mkdir()
    _seed_memory(wf)

    runner = _make_runner(wf, auto_curation=False)
    first = runner._build_manager_task("some task", {}, iteration=1)
    assert "PRIOR RUN MEMORY" not in first


def test_prior_memory_skipped_for_submanager(tmp_path):
    wf = tmp_path / "wf"
    wf.mkdir()
    _seed_memory(wf)

    runner = _make_runner(wf, auto_curation=True)
    # Simulate being a submanager by setting a parent digest sha.
    runner._parent_digest_sha = "deadbeef" * 4
    first = runner._build_manager_task("some task", {}, iteration=1)
    assert "PRIOR RUN MEMORY" not in first
