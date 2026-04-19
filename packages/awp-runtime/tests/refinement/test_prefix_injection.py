"""Verify manager_prompt_prefix reaches iteration 1's user message only.

Strategy: run the workflow with a real ``DelegationLoopRunner`` but
stub the LLM's ``chat_stream_json`` / ``chat_json`` so no real API
call happens. The stub captures the ``messages`` argument that the
runner constructed, which lets us assert on the production user-
message contents (the prefix is prepended inside ``_run_inline_manager``
before messages are built).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from awp.data.workflow import AgentWorkflow


@pytest.fixture(autouse=True)
def _preserve_env():
    """AgentWorkflow.run() leaks API-key env vars from ~/.awp/.env into
    ``os.environ`` globally. Snapshot and restore to avoid poisoning
    sibling tests (e.g. ``test_runtime.py::test_ollama_no_key_needed``)."""
    keys = (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_PROVIDER",
        "GROQ_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "MISTRAL_API_KEY",
    )
    saved = {k: os.environ.get(k) for k in keys}
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _stub_llm_and_capture_messages(
    tmp_path: Path, *, manager_prompt_prefix: str | None, max_loops: int = 1
) -> list[list[dict]]:
    """Return a list of the ``messages`` argument for each LLM call."""
    captured: list[list[dict]] = []

    def fake_chat(self, messages, *args, **kwargs):
        # Deep-copy the messages so later mutations don't alter our capture.
        captured.append([{**m} for m in messages])
        # Return a COMPLETE decision so the loop exits on iteration 1.
        return {
            "decision": "complete",
            "final_result": {"done": True, "confidence": 0.9},
            "confidence": 0.9,
        }

    from awp.runtime.llm import LLMClient

    with (
        patch.object(LLMClient, "chat_json", fake_chat),
        patch.object(
            LLMClient,
            "chat_stream_json",
            side_effect=Exception("stream off — fall back"),
        ),
    ):
        wf = AgentWorkflow(
            inputs={},
            task="do the thing",
            model="openai/gpt-5-mini",
            output_dir=str(tmp_path),
            manager_prompt_prefix=manager_prompt_prefix,
            max_loops=max_loops,
            max_total_tokens=1000,
            max_wall_time=30,
            critique_enabled=False,
            planning_enabled=False,
            diagnosis_enabled=False,
        )
        wf.run()

    return captured


def test_prefix_injected_into_iteration_1_user_message(tmp_path: Path) -> None:
    prefix = "## REFINEMENT CONTEXT\nfix defect X"
    captured = _stub_llm_and_capture_messages(tmp_path, manager_prompt_prefix=prefix, max_loops=1)
    assert captured, "LLM was never called"
    first_messages = captured[0]
    user_msg = next(m["content"] for m in first_messages if m["role"] == "user")
    assert "REFINEMENT CONTEXT" in user_msg, "prefix missing from iter 1"


def test_no_prefix_leaves_message_unchanged(tmp_path: Path) -> None:
    captured = _stub_llm_and_capture_messages(tmp_path, manager_prompt_prefix=None, max_loops=1)
    assert captured
    user_msg = next(m["content"] for m in captured[0] if m["role"] == "user")
    assert "REFINEMENT CONTEXT" not in user_msg


def test_runner_stores_manager_prompt_prefix_attribute(tmp_path: Path) -> None:
    """Infrastructure check: AgentWorkflow carries the prefix to the runner."""
    wf = AgentWorkflow(
        inputs={},
        task="t",
        model="openai/gpt-5-mini",
        output_dir=str(tmp_path),
        manager_prompt_prefix="## REFINEMENT CONTEXT\nxxx",
        max_loops=1,
        max_total_tokens=100,
        max_wall_time=5,
        critique_enabled=False,
    )
    assert wf.manager_prompt_prefix == "## REFINEMENT CONTEXT\nxxx"
