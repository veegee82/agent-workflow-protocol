"""Integration-style test for Hierarchical Context Digest injection.

We bypass the full runner constructor (it pulls in an LLM client, a
tool registry, and a workflow dir) and drive `_build_manager_task`
directly on a lightweight object that carries just the fields the
method actually reads. This is faithful to what S4 will need: a
confirmation that the digest lifecycle (generate -> store -> inject)
works end-to-end with real :class:`DigestStore` I/O, no LLM calls.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from awp.runtime.delegation_loop_runner import DelegationLoopRunner
from awp.runtime.digest import (
    DigestStore,
    build_digest_from_iteration,
)


class _FakeBudget:
    def to_dict(self) -> dict:
        return {"loops_used": 1, "max_loops": 10}


def _make_runner_like(tmp_path: Path) -> SimpleNamespace:
    store = DigestStore(workspace=tmp_path / "runs" / "r1")
    history_cfg = SimpleNamespace(full_results_window=5)
    config = SimpleNamespace(
        history=history_cfg,
        digest_enabled=True,
        digest_mode="deterministic",
        digest_max_depth=1,
        blackboard_enabled=False,
    )
    obj = SimpleNamespace(
        _blackboard=None,
        _last_blackboard_seen_id=None,
        _budget=_FakeBudget(),
        _history=[],
        _config=config,
        _digest_store=store,
        _current_digest=None,
        _current_digest_sha=None,
        _pending_child_digest_hashes=[],
        _run_id="r1",
        _critique_engine=None,
        _task_plan=None,
        _journal=None,
        _planning_enabled=False,
        _diagnosis_enabled=False,
        _tools=None,
        _dir=tmp_path,
        _build_output_dir_listing=lambda: "",
        _build_intelligence_task_sections=lambda state, iteration: "",
    )
    return obj


def test_manager_prompt_injects_my_digest_on_second_iteration(tmp_path: Path) -> None:
    obj = _make_runner_like(tmp_path)

    # --- Iteration 1: no digest yet, prompt should NOT contain MY DIGEST ---
    prompt_1 = DelegationLoopRunner._build_manager_task(
        obj, "Investigate X", {}, 1  # type: ignore[arg-type]
    )
    assert "MY DIGEST" not in prompt_1

    # Simulate iteration 1 completing: build + store digest
    history_entry_1 = {"iteration": 1, "confidence": 0.9}
    delegation_results_1 = [
        {
            "worker_id": "w1",
            "result": {"confidence": 0.9, "summary": "X uses REST API"},
        },
    ]
    obj._history.append(history_entry_1)
    d1 = build_digest_from_iteration(
        history_entry=history_entry_1,
        prior_digest=None,
        run_id=obj._run_id,
        iteration=1,
        delegation_results=delegation_results_1,
        original_task="Investigate X",
    )
    sha1 = obj._digest_store.put(d1)
    obj._current_digest = d1
    obj._current_digest_sha = sha1

    # --- Iteration 2: prompt MUST now contain MY DIGEST + key fact ---
    prompt_2 = DelegationLoopRunner._build_manager_task(
        obj, "Investigate X", {}, 2  # type: ignore[arg-type]
    )
    assert "## MY DIGEST" in prompt_2
    assert "X uses REST API" in prompt_2
    assert sha1[:12] in prompt_2


def test_children_digests_block_rendered(tmp_path: Path) -> None:
    obj = _make_runner_like(tmp_path)

    # Create a child digest, put it in the store.
    child = build_digest_from_iteration(
        history_entry={"confidence": 0.7},
        prior_digest=None,
        run_id="child",
        iteration=1,
        delegation_results=[],
        original_task="child goal details",
    )
    child_sha = obj._digest_store.put(child)

    # Parent iter 1 digest with the child sha folded in.
    parent = build_digest_from_iteration(
        history_entry={"confidence": 0.8},
        prior_digest=None,
        run_id=obj._run_id,
        iteration=1,
        delegation_results=[],
        original_task="parent goal",
    )
    parent.child_digest_hashes = [child_sha]
    parent_sha = obj._digest_store.put(parent)
    obj._current_digest = parent
    obj._current_digest_sha = parent_sha
    obj._history.append({"iteration": 1, "confidence": 0.8})

    prompt = DelegationLoopRunner._build_manager_task(
        obj, "parent goal", {}, 2  # type: ignore[arg-type]
    )
    assert "CHILDREN DIGESTS" in prompt
    assert child_sha[:12] in prompt
    assert "child goal details" in prompt


def test_digest_disabled_skips_injection(tmp_path: Path) -> None:
    obj = _make_runner_like(tmp_path)
    obj._config.digest_enabled = False

    # Even if a digest is present, disabled flag must suppress the block.
    obj._current_digest = build_digest_from_iteration(
        history_entry={"confidence": 0.5},
        prior_digest=None,
        run_id="r1",
        iteration=1,
        delegation_results=[],
        original_task="t",
    )
    obj._current_digest_sha = "x" * 64
    obj._history.append({"iteration": 1, "confidence": 0.5})

    prompt = DelegationLoopRunner._build_manager_task(
        obj, "t", {}, 2  # type: ignore[arg-type]
    )
    assert "MY DIGEST" not in prompt
