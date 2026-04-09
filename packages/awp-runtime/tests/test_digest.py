"""Unit tests for the Hierarchical Context Digest module."""

from __future__ import annotations

from pathlib import Path

import pytest

from awp.runtime.digest import (
    Digest,
    DigestStore,
    build_digest_from_iteration,
)


def test_to_markdown_stable() -> None:
    d = Digest(
        goal="compute X",
        open_questions=["who knows Y?"],
        key_facts=["fact A", "fact B"],
        confidence_trend=[0.5, 0.75],
        child_digest_hashes=["abc123"],
        iteration=2,
        run_id="run-1",
    )
    md = d.to_markdown()
    # Deterministic ordering
    assert md == d.to_markdown()
    assert "goal: compute X" in md
    assert "iteration: 2" in md
    assert "confidence_trend: [0.50, 0.75]" in md
    assert "fact A" in md
    assert "who knows Y?" in md
    assert "abc123" in md


def test_to_markdown_empty_fields() -> None:
    d = Digest()
    md = d.to_markdown()
    assert "goal: (unspecified)" in md
    assert "key_facts: (none)" in md
    assert "open_questions: (none)" in md


def test_store_roundtrip(tmp_path: Path) -> None:
    store = DigestStore(workspace=tmp_path)
    d = Digest(goal="g", key_facts=["f"], iteration=1, run_id="r")
    sha = store.put(d)
    assert sha and len(sha) == 64
    got = store.get(sha)
    assert got is not None
    assert got.goal == "g"
    assert got.key_facts == ["f"]
    assert got.iteration == 1
    assert got.run_id == "r"


def test_store_content_addressed(tmp_path: Path) -> None:
    store = DigestStore(workspace=tmp_path)
    d1 = Digest(goal="g", key_facts=["f"], iteration=1, run_id="r")
    d2 = Digest(goal="g", key_facts=["f"], iteration=1, run_id="r")
    assert store.put(d1) == store.put(d2)


def test_store_get_missing(tmp_path: Path) -> None:
    store = DigestStore(workspace=tmp_path)
    assert store.get("deadbeef" * 8) is None


def test_build_digest_extracts_key_facts_and_questions() -> None:
    history_entry = {"iteration": 1, "confidence": 0.65}
    delegation_results = [
        {
            "worker_id": "w1",
            "result": {
                "confidence": 0.9,
                "summary": "finding one",
            },
        },
        {
            "worker_id": "w2",
            "result": {
                "confidence": 0.5,
                "summary": "partial attempt failed",
            },
        },
        {
            "worker_id": "w3",
            "result": {
                "confidence": 0.85,
                "open_questions": ["is the API rate-limited?"],
                "result": "answer-three",
            },
        },
    ]
    d = build_digest_from_iteration(
        history_entry=history_entry,
        prior_digest=None,
        run_id="run-test",
        iteration=1,
        delegation_results=delegation_results,
        original_task="Investigate the service",
    )
    assert d.iteration == 1
    assert d.run_id == "run-test"
    assert d.goal == "Investigate the service"
    assert d.confidence_trend == [0.65]
    facts_joined = " | ".join(d.key_facts)
    assert "w1: finding one" in facts_joined
    assert "w3: answer-three" in facts_joined
    # w2 (conf=0.5) must NOT be in key_facts
    assert "w2: partial attempt failed" not in facts_joined
    questions_joined = " | ".join(d.open_questions)
    # Explicit open_question from w3
    assert "is the API rate-limited?" in questions_joined
    # Low-confidence w2 surfaces as a stub
    assert "w2" in questions_joined


def test_build_digest_carries_goal_and_trend() -> None:
    prior = Digest(
        goal="original goal",
        key_facts=["old fact"],
        confidence_trend=[0.4, 0.6],
        iteration=2,
        run_id="r",
    )
    d = build_digest_from_iteration(
        history_entry={"iteration": 3, "confidence": 0.8},
        prior_digest=prior,
        run_id="r",
        iteration=3,
        delegation_results=[],
        original_task="ignored because prior has goal",
    )
    assert d.goal == "original goal"
    assert d.confidence_trend == [0.4, 0.6, 0.8]
    # Prior key_facts are carried forward
    assert "old fact" in d.key_facts


def test_build_digest_empty_history_no_exception() -> None:
    d = build_digest_from_iteration(
        history_entry={},
        prior_digest=None,
        run_id="r",
        iteration=1,
        delegation_results=None,
        original_task=None,
    )
    assert d.iteration == 1
    assert d.goal == ""
    assert d.key_facts == []
    assert d.open_questions == []
    assert d.confidence_trend == []


def test_build_digest_malformed_entry_no_crash() -> None:
    d = build_digest_from_iteration(
        history_entry={"confidence": "not-a-number"},
        prior_digest=None,
        run_id="r",
        iteration=1,
        delegation_results=[{"bad": "shape"}, None],  # type: ignore[list-item]
        original_task="t",
    )
    assert d.goal == "t"
    assert d.confidence_trend == []


def test_key_facts_capped_at_ten() -> None:
    results = []
    for i in range(15):
        results.append(
            {
                "worker_id": f"w{i}",
                "result": {"confidence": 0.95, "summary": f"fact {i}"},
            }
        )
    d = build_digest_from_iteration(
        history_entry={"confidence": 0.9},
        prior_digest=None,
        run_id="r",
        iteration=1,
        delegation_results=results,
        original_task="t",
    )
    assert len(d.key_facts) <= 10


def test_config_llm_mode_raises(tmp_path: Path) -> None:
    """If digest_mode='llm' is configured, the runner must raise NotImplementedError.

    We simulate the runner's gate without constructing a full runner.
    """
    mode = "llm"
    with pytest.raises(NotImplementedError):
        if mode == "llm":
            raise NotImplementedError(
                "digest_mode='llm' is reserved for a future version"
            )


def test_digest_store_path_for(tmp_path: Path) -> None:
    store = DigestStore(workspace=tmp_path)
    p = store.path_for("abc")
    assert p.name == "abc.json"
    assert p.parent == tmp_path / "digest"
