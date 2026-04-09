"""Unit tests for:

- Baustein 5: content-aware :meth:`DelegationLoopRunner._delegation_signature`
- Baustein 2: default submanager state inheritance (inherit-all with
  selective-forget blacklist, explicit whitelist override still wins).
"""
from __future__ import annotations

import hashlib

import pytest

from awp.runtime.delegation_loop_runner import DelegationLoopRunner


# ---------------------------------------------------------------------------
# Baustein 5 — Content-aware delegation signature
# ---------------------------------------------------------------------------


def _legacy_sig(instructions: str) -> str:
    norm = DelegationLoopRunner._normalize_instructions(instructions)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def test_signature_same_instructions_same_context_are_equal():
    env_a = {"instructions": "analyze dataset", "context": {"path": "/a.csv", "rows": 10}}
    env_b = {"instructions": "analyze dataset", "context": {"rows": 10, "path": "/a.csv"}}
    assert DelegationLoopRunner._delegation_signature([env_a]) == \
        DelegationLoopRunner._delegation_signature([env_b])


def test_signature_same_instructions_different_context_differ():
    env_a = {"instructions": "analyze dataset", "context": {"path": "/a.csv"}}
    env_b = {"instructions": "analyze dataset", "context": {"path": "/b.csv"}}
    sig_a = DelegationLoopRunner._delegation_signature([env_a])
    sig_b = DelegationLoopRunner._delegation_signature([env_b])
    assert sig_a != sig_b


def test_signature_empty_context_matches_legacy():
    instructions = "Summarize the findings"
    env = {"instructions": instructions}
    sig = DelegationLoopRunner._delegation_signature([env])
    assert sig == (_legacy_sig(instructions),)


def test_signature_empty_dict_context_matches_legacy():
    instructions = "Summarize"
    env = {"instructions": instructions, "context": {}}
    sig = DelegationLoopRunner._delegation_signature([env])
    assert sig == (_legacy_sig(instructions),)


def test_signature_inherited_state_keys_affect_signature():
    env_a = {"instructions": "do it", "inherited_state_keys": ["x"]}
    env_b = {"instructions": "do it", "inherited_state_keys": ["y"]}
    env_none = {"instructions": "do it"}
    sig_a = DelegationLoopRunner._delegation_signature([env_a])
    sig_b = DelegationLoopRunner._delegation_signature([env_b])
    sig_none = DelegationLoopRunner._delegation_signature([env_none])
    assert sig_a != sig_b
    assert sig_a != sig_none
    assert sig_none == (_legacy_sig("do it"),)


# ---------------------------------------------------------------------------
# Baustein 2 — Default inheritance + selective forget
# ---------------------------------------------------------------------------


class _FakeConfig:
    def __init__(self, forbidden: list[str] | None = None):
        self.forbidden_inheritance_keys = list(forbidden or [])


def _build_inherited(envelope: dict, state: dict, cfg=None) -> dict:
    """Re-implements the inheritance block of ``_spawn_submanager`` so the
    pure inheritance logic can be unit-tested without spinning up a full
    DelegationLoopRunner (which requires a workflow on disk)."""
    whitelist = envelope.get("inherited_state_keys")
    if isinstance(whitelist, (list, tuple)) and len(whitelist) > 0:
        return {k: state.get(k) for k in whitelist if k in state}
    forbidden_env = envelope.get("forbidden_inheritance_keys") or []
    forbidden_cfg = list(getattr(cfg, "forbidden_inheritance_keys", []) or [])
    forbidden = set()
    for item in list(forbidden_env) + forbidden_cfg:
        if isinstance(item, str):
            forbidden.add(item)
    return {k: v for k, v in (state or {}).items() if k not in forbidden}


def test_inheritance_default_passes_everything():
    state = {"a": 1, "b": 2, "c": 3}
    inherited = _build_inherited({}, state)
    assert inherited == state


def test_inheritance_explicit_whitelist_still_wins():
    state = {"a": 1, "b": 2, "c": 3}
    env = {"inherited_state_keys": ["a", "c", "missing"]}
    inherited = _build_inherited(env, state)
    assert inherited == {"a": 1, "c": 3}


def test_inheritance_blacklist_strips_listed_keys():
    state = {"public": 1, "secret_token": "xxx", "data": "ok"}
    env = {"forbidden_inheritance_keys": ["secret_token"]}
    inherited = _build_inherited(env, state)
    assert inherited == {"public": 1, "data": "ok"}


def test_inheritance_blacklist_from_config():
    state = {"a": 1, "b": 2}
    cfg = _FakeConfig(forbidden=["b"])
    inherited = _build_inherited({}, state, cfg=cfg)
    assert inherited == {"a": 1}


def test_inheritance_whitelist_overrides_blacklist():
    state = {"a": 1, "b": 2, "c": 3}
    cfg = _FakeConfig(forbidden=["b"])
    env = {"inherited_state_keys": ["a", "b"]}
    inherited = _build_inherited(env, state, cfg=cfg)
    # whitelist wins — 'b' is included despite being blacklisted
    assert inherited == {"a": 1, "b": 2}


def test_config_field_exists_and_defaults_empty():
    from awp.models.orchestration import DelegationLoopConfig

    cfg = DelegationLoopConfig()
    assert cfg.forbidden_inheritance_keys == []
    cfg2 = DelegationLoopConfig(forbidden_inheritance_keys=["secret"])
    assert cfg2.forbidden_inheritance_keys == ["secret"]
