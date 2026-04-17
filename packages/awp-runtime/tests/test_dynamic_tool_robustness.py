"""Robustness tests for runtime dynamic tool generation.

Covers the six robustness building blocks (B1-B6):
  - B2 schema↔signature consistency
  - B3 dry-run probe
  - B4 inline LLM repair loop
  - B5 content-addressable cache
  - B6 structured errors / metrics / configurable timeout
  - import-alternative hints

These tests are intentionally edge-case heavy: they exercise the
validation pipeline with the kinds of broken outputs an LLM commonly
produces.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from awp.runtime.code_executor import CodeExecutor
from awp.runtime.dynamic_tool_factory import (
    DynamicToolFactory,
    compute_tool_hash,
)
from awp.runtime.tool_repair import attempt_repair
from awp.runtime.tools import ToolRegistry


@pytest.fixture()
def factory(tmp_path: Path) -> DynamicToolFactory:
    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=tmp_path, max_timeout=15)
    registry.set_code_executor(executor)
    return DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={
            "enabled": True,
            "allowed_namespaces": ["dyn"],
            "dry_run": True,
            "cache": True,
            "timeout_seconds": 8,
        },
        workflow_dir=tmp_path,
        sandbox_type="subprocess",
    )


# ---------------------------------------------------------------------------
# B5 — content-addressable hash
# ---------------------------------------------------------------------------


def test_compute_hash_is_stable():
    code = "def handler(*, x):\n    return {'ok': True, 'data': {'x': x}}\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    h1 = compute_tool_hash("dyn.echo", code, params)
    h2 = compute_tool_hash("dyn.echo", code + "  \n", params)  # trailing ws
    h3 = compute_tool_hash(
        "dyn.echo", code, {"properties": {"x": {"type": "integer"}}, "type": "object"}
    )  # reordered keys
    assert h1 == h2 == h3
    assert len(h1) == 64


def test_compute_hash_changes_with_code():
    p = {"type": "object", "properties": {}}
    a = compute_tool_hash("dyn.x", "def handler(*, ):\n    return {'ok': True}", p)
    b = compute_tool_hash("dyn.x", "def handler(*, ):\n    return {'ok': False}", p)
    assert a != b


def test_cache_hit_on_second_create(factory: DynamicToolFactory):
    code = (
        "def handler(*, value):\n"
        "    return {'ok': True, 'status': 200, 'data': {'v': value}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }
    r1 = factory.create_tool(
        name="dyn.cached",
        description="echo",
        parameters=params,
        code=code,
        creator_agent="agent_a",
        allowed_namespace="dyn",
    )
    assert r1["ok"]
    assert r1["data"].get("cache_hit") is not True

    r2 = factory.create_tool(
        name="dyn.cached",
        description="echo (re-creation by another agent)",
        parameters=params,
        code=code,
        creator_agent="agent_b",
        allowed_namespace="dyn",
    )
    assert r2["ok"]
    assert r2["data"]["cache_hit"] is True
    assert factory.metrics["cache_hits"] == 1
    assert factory.metrics["successes"] == 2


# ---------------------------------------------------------------------------
# B2 — schema↔signature consistency
# ---------------------------------------------------------------------------


def test_schema_missing_handler_kwarg(factory: DynamicToolFactory):
    """Handler reads `weight` but schema doesn't declare it."""
    code = (
        "def handler(*, value, weight):\n"
        "    return {'ok': True, 'status': 200, 'data': {'p': value*weight}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }
    r = factory.create_tool(
        name="dyn.bad_schema",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert not r["ok"]
    assert r.get("category") == "schema_mismatch"
    assert r.get("repairable") is True
    assert "weight" in r["error"]
    assert factory.metrics["schema_mismatches"] == 1


def test_schema_kwargs_get_access(factory: DynamicToolFactory):
    """Handler uses **kwargs and reads via .get — must be detected."""
    code = (
        "def handler(**kwargs):\n"
        "    a = kwargs.get('alpha', 0)\n"
        "    b = kwargs['beta']\n"
        "    return {'ok': True, 'status': 200, 'data': {'sum': a+b}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"alpha": {"type": "integer"}},
    }
    r = factory.create_tool(
        name="dyn.kwargs_bad",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert not r["ok"]
    assert "beta" in r["error"]


def test_schema_unused_property_warning_only(factory: DynamicToolFactory, caplog):
    """Schema declares an extra param the handler ignores — warn, but pass."""
    code = (
        "def handler(*, x):\n"
        "    return {'ok': True, 'status': 200, 'data': {'x': x}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "unused": {"type": "string"},
        },
        "required": ["x"],
    }
    r = factory.create_tool(
        name="dyn.unused_ok",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert r["ok"], r.get("error")


def test_schema_secrets_kwargs_not_required_in_schema(factory: DynamicToolFactory):
    """Reading `_secrets` must NOT trip the schema check."""
    code = (
        "def handler(*, query):\n"
        "    key = _secrets.get('FAKE_KEY', '')\n"
        "    return {'ok': True, 'status': 200, 'data': {'q': query, 'k': bool(key)}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    r = factory.create_tool(
        name="dyn.with_secrets",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
        required_secrets=["FAKE_KEY"],
    )
    assert r["ok"], r.get("error")


# ---------------------------------------------------------------------------
# B3 — dry-run probe
# ---------------------------------------------------------------------------


def test_dry_run_catches_handler_crash(factory: DynamicToolFactory):
    """Handler crashes on empty input — dry-run rejects before registration."""
    code = (
        "def handler(*, items):\n"
        "    first = items[0]  # IndexError on empty list\n"
        "    return {'ok': True, 'status': 200, 'data': {'first': first}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }
    r = factory.create_tool(
        name="dyn.crashy",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert not r["ok"]
    assert r.get("category") == "dry_run"
    assert factory.metrics["dry_run_failures"] == 1
    # Tool was NOT registered:
    assert "dyn.crashy" not in factory._registry._tools


def test_dry_run_passes_safe_handler(factory: DynamicToolFactory):
    code = (
        "def handler(*, items):\n"
        "    if not items:\n"
        "        return {'ok': True, 'status': 200, 'data': {'count': 0}, 'error': None}\n"
        "    return {'ok': True, 'status': 200, 'data': {'count': len(items)}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }
    r = factory.create_tool(
        name="dyn.safe",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert r["ok"], r.get("error")


def test_dry_run_disabled_via_config(tmp_path: Path):
    """When dry_run=false, broken tools register anyway (legacy behaviour)."""
    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=tmp_path, max_timeout=15)
    registry.set_code_executor(executor)
    f = DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={
            "enabled": True,
            "allowed_namespaces": ["dyn"],
            "dry_run": False,
        },
        workflow_dir=tmp_path,
    )
    code = (
        "def handler(*, items):\n"
        "    return {'ok': True, 'status': 200, 'data': {'first': items[0]}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"items": {"type": "array"}},
        "required": ["items"],
    }
    r = f.create_tool(
        name="dyn.no_dry",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert r["ok"]


# ---------------------------------------------------------------------------
# B6 — error classification + import alternatives
# ---------------------------------------------------------------------------


def test_forbidden_import_includes_alternative(factory: DynamicToolFactory):
    code = (
        "import os\n"
        "def handler(*, path):\n"
        "    return {'ok': True, 'status': 200, 'data': {'p': path}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }
    r = factory.create_tool(
        name="dyn.import_os",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert not r["ok"]
    assert r["status"] == 403
    assert r.get("category") == "import"
    assert "Alternative" in r["error"]
    assert factory.metrics["import_failures"] == 1


def test_missing_return_categorized_as_validation(factory: DynamicToolFactory):
    code = "def handler(*, x):\n    pass\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    r = factory.create_tool(
        name="dyn.no_return",
        description="x",
        parameters=params,
        code=code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert not r["ok"]
    assert r.get("category") == "validation"


def test_metrics_attempts_increment(factory: DynamicToolFactory):
    code = "def handler(*, x):\n    return {'ok': True, 'status': 200, 'data': {}, 'error': None}\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    factory.create_tool(
        name="dyn.m1", description="x", parameters=params, code=code,
        creator_agent="a", allowed_namespace="dyn",
    )
    factory.create_tool(
        name="dyn.m2", description="x", parameters=params, code=code,
        creator_agent="a", allowed_namespace="dyn",
    )
    assert factory.metrics["attempts"] == 2
    assert factory.metrics["successes"] == 2


# ---------------------------------------------------------------------------
# B4 — repair loop
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Minimal stub of LLMClient for repair loop tests."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        if not self.responses:
            return {"_parse_failure": True}
        return self.responses.pop(0)


def test_repair_fixes_schema_mismatch(factory: DynamicToolFactory):
    bad_code = (
        "def handler(*, value, weight):\n"
        "    return {'ok': True, 'status': 200, 'data': {'p': value*weight}, 'error': None}\n"
    )
    bad_params = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }
    failed = factory.create_tool(
        name="dyn.repair_me",
        description="x",
        parameters=bad_params,
        code=bad_code,
        creator_agent="agent",
        allowed_namespace="dyn",
    )
    assert not failed["ok"]
    assert failed["category"] == "schema_mismatch"

    fixed_params = {
        "type": "object",
        "properties": {
            "value": {"type": "integer"},
            "weight": {"type": "number"},
        },
        "required": ["value", "weight"],
    }
    llm = _FakeLLM(
        [
            {
                "name": "dyn.repair_me",
                "description": "fixed",
                "parameters": fixed_params,
                "code": bad_code,
            }
        ]
    )
    repaired = attempt_repair(
        llm_client=llm,
        factory=factory,
        tool_spec={
            "name": "dyn.repair_me",
            "description": "x",
            "parameters": bad_params,
            "code": bad_code,
        },
        failed_result=failed,
        creator_agent="agent",
        namespace="dyn",
        max_tools=10,
    )
    assert repaired["ok"], repaired
    assert repaired["repaired"] is True
    assert repaired["repair_attempts"] == 1
    assert factory.metrics["repair_successes"] == 1
    assert len(llm.calls) == 1


def test_repair_fixes_forbidden_import(factory: DynamicToolFactory):
    bad_code = (
        "import os\n"
        "def handler(*, path):\n"
        "    return {'ok': True, 'status': 200, 'data': {'p': path}, 'error': None}\n"
    )
    params = {"type": "object", "properties": {"path": {"type": "string"}}}
    failed = factory.create_tool(
        name="dyn.import_repair", description="x", parameters=params, code=bad_code,
        creator_agent="agent", allowed_namespace="dyn",
    )
    assert not failed["ok"]
    fixed_code = (
        "def handler(*, path):\n"
        "    return {'ok': True, 'status': 200, 'data': {'p': path}, 'error': None}\n"
    )
    llm = _FakeLLM([{"name": "dyn.import_repair", "code": fixed_code, "parameters": params, "description": "fixed"}])
    repaired = attempt_repair(
        llm_client=llm, factory=factory,
        tool_spec={"name": "dyn.import_repair", "description": "x", "parameters": params, "code": bad_code},
        failed_result=failed, creator_agent="agent", namespace="dyn", max_tools=10,
    )
    assert repaired["ok"], repaired


def test_repair_gives_up_after_max_attempts(factory: DynamicToolFactory):
    bad_code = "def handler(value, weight):\n    return value*weight\n"  # positional + missing return dict
    params = {
        "type": "object",
        "properties": {"value": {"type": "integer"}, "weight": {"type": "number"}},
    }
    failed = factory.create_tool(
        name="dyn.unfixable", description="x", parameters=params, code=bad_code,
        creator_agent="agent", allowed_namespace="dyn",
    )
    assert not failed["ok"]
    # LLM keeps producing the same broken code
    broken_responses = [
        {"name": "dyn.unfixable", "code": bad_code, "parameters": params}
    ] * 5
    llm = _FakeLLM(broken_responses)
    repaired = attempt_repair(
        llm_client=llm, factory=factory,
        tool_spec={"name": "dyn.unfixable", "description": "x", "parameters": params, "code": bad_code},
        failed_result=failed, creator_agent="agent", namespace="dyn", max_tools=10,
        max_attempts=2,
    )
    assert not repaired["ok"]
    assert factory.metrics["repair_attempts"] == 2
    assert factory.metrics["repair_successes"] == 0


def test_repair_skipped_when_no_llm(factory: DynamicToolFactory):
    failed = {"ok": False, "error": "x", "category": "validation", "repairable": True}
    out = attempt_repair(
        llm_client=None, factory=factory,
        tool_spec={"name": "dyn.x"}, failed_result=failed,
        creator_agent="a", namespace="dyn", max_tools=10,
    )
    assert out is failed


def test_repair_skipped_when_not_repairable(factory: DynamicToolFactory):
    failed = {"ok": False, "error": "policy", "category": "policy", "repairable": False}
    llm = _FakeLLM([{"name": "x"}])
    out = attempt_repair(
        llm_client=llm, factory=factory,
        tool_spec={"name": "dyn.x"}, failed_result=failed,
        creator_agent="a", namespace="dyn", max_tools=10,
    )
    assert out is failed
    assert llm.calls == []


# ---------------------------------------------------------------------------
# Edge cases — multiple tools, namespace handling, hash collisions
# ---------------------------------------------------------------------------


def test_two_distinct_tools_get_distinct_hashes(factory: DynamicToolFactory):
    code1 = "def handler(*, x):\n    return {'ok': True, 'status': 200, 'data': {'x': x}, 'error': None}\n"
    code2 = "def handler(*, x):\n    return {'ok': True, 'status': 200, 'data': {'x': x*2}, 'error': None}\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    r1 = factory.create_tool("dyn.t1", "x", params, code1, "a", allowed_namespace="dyn")
    r2 = factory.create_tool("dyn.t2", "x", params, code2, "a", allowed_namespace="dyn")
    assert r1["ok"] and r2["ok"]
    assert r1["data"]["code_hash"] != r2["data"]["code_hash"]


def test_no_handler_function(factory: DynamicToolFactory):
    code = "def helper(x):\n    return x\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    r = factory.create_tool("dyn.no_handler", "x", params, code, "a", allowed_namespace="dyn")
    assert not r["ok"]
    assert "handler" in r["error"]


def test_two_handlers_rejected(factory: DynamicToolFactory):
    code = (
        "def handler(*, x):\n    return {'ok': True}\n"
        "def handler(*, y):\n    return {'ok': True}\n"
    )
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    r = factory.create_tool("dyn.two", "x", params, code, "a", allowed_namespace="dyn")
    assert not r["ok"]


def test_invalid_namespace_rejected(factory: DynamicToolFactory):
    code = "def handler(*, x):\n    return {'ok': True, 'status': 200, 'data': {}, 'error': None}\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    r = factory.create_tool("other.x", "x", params, code, "a", allowed_namespace="dyn")
    assert not r["ok"]
    assert r["status"] == 403


def test_reserved_namespace_rejected(factory: DynamicToolFactory):
    code = "def handler(*, x):\n    return {'ok': True, 'status': 200, 'data': {}, 'error': None}\n"
    params = {"type": "object", "properties": {"x": {"type": "integer"}}}
    r = factory.create_tool("web.x", "x", params, code, "a", allowed_namespace="web")
    assert not r["ok"]
    assert "reserved" in r["error"].lower()


def test_synth_inputs_covers_types(factory: DynamicToolFactory):
    schema = {
        "type": "object",
        "properties": {
            "s": {"type": "string"},
            "i": {"type": "integer"},
            "n": {"type": "number"},
            "b": {"type": "boolean"},
            "a": {"type": "array"},
            "o": {"type": "object"},
            "e": {"type": "string", "enum": ["alpha", "beta"]},
            "d": {"type": "string", "default": "preset"},
        },
    }
    out = factory._synth_inputs_from_schema(schema)
    assert out == {
        "s": "", "i": 0, "n": 0, "b": False,
        "a": [], "o": {},
        "e": "alpha", "d": "preset",
    }


def test_handler_signature_check_keeps_legacy_strict_mode(factory: DynamicToolFactory):
    """Positional args still rejected by validate_code (existing behaviour)."""
    code = "def handler(x, y):\n    return {'ok': True}\n"
    r = factory.validate_code(code, namespace="dyn")
    assert not r["ok"]


# ---------------------------------------------------------------------------
# Integration: full _process_tool_creation pipeline with a fake LLM
# (covers prompt → factory → validate → dry-run → repair → register)
# ---------------------------------------------------------------------------


def test_process_tool_creation_end_to_end_with_repair(tmp_path: Path):
    """Simulate a worker that produces a broken tool; pipeline should
    invoke the repair loop and end with a registered, working tool."""
    from awp.runtime.delegation_loop_runner import DelegationLoopRunner
    from awp.runtime.tools import ToolRegistry

    # Build a real factory + tool registry
    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=tmp_path, max_timeout=15)
    registry.set_code_executor(executor)
    factory = DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={"enabled": True, "allowed_namespaces": ["dyn"], "dry_run": True},
        workflow_dir=tmp_path,
    )
    registry._dynamic_tool_factory = factory

    # Stub a minimal runner that exposes _process_tool_creation
    runner = DelegationLoopRunner.__new__(DelegationLoopRunner)
    runner._tools = registry
    runner._budget = type("B", (), {"tokens_consumed": 0})()

    fixed_code = (
        "def handler(*, value, weight):\n"
        "    return {'ok': True, 'status': 200, 'data': {'p': value*weight}, 'error': None}\n"
    )
    fixed_params = {
        "type": "object",
        "properties": {
            "value": {"type": "integer"},
            "weight": {"type": "number"},
        },
        "required": ["value", "weight"],
    }
    llm = _FakeLLM(
        [
            {
                "name": "dyn.product",
                "description": "fixed",
                "parameters": fixed_params,
                "code": fixed_code,
            }
        ]
    )

    broken_spec = {
        "name": "dyn.product",
        "description": "compute product",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
        },
        "code": fixed_code,  # handler reads `weight` but schema doesn't declare it
    }

    result = {"tools_created": [broken_spec]}
    runner._process_tool_creation(
        result,
        worker_id="worker_1",
        codemode={"tool_creation_namespace": "dyn", "max_tools": 5, "repair_attempts": 2},
        llm_client=llm,
    )

    registered = result.get("tools_registered", [])
    assert len(registered) == 1
    rec = registered[0]
    assert rec["registered"] is True
    assert rec.get("repaired") is True
    assert rec.get("repair_attempts") == 1
    # Tool is actually callable now:
    assert "dyn.product" in registry._tools
    assert factory.metrics["repair_successes"] == 1


def test_process_tool_creation_succeeds_first_try(tmp_path: Path):
    from awp.runtime.delegation_loop_runner import DelegationLoopRunner
    from awp.runtime.tools import ToolRegistry

    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=tmp_path, max_timeout=15)
    registry.set_code_executor(executor)
    factory = DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={"enabled": True, "allowed_namespaces": ["dyn"]},
        workflow_dir=tmp_path,
    )
    registry._dynamic_tool_factory = factory
    runner = DelegationLoopRunner.__new__(DelegationLoopRunner)
    runner._tools = registry
    runner._budget = type("B", (), {"tokens_consumed": 0})()

    spec = {
        "name": "dyn.add",
        "description": "add two numbers",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
        "code": (
            "def handler(*, a, b):\n"
            "    return {'ok': True, 'status': 200, 'data': {'sum': a+b}, 'error': None}\n"
        ),
    }
    result = {"tools_created": [spec]}
    runner._process_tool_creation(
        result,
        worker_id="w",
        codemode={"tool_creation_namespace": "dyn"},
        llm_client=None,
    )
    assert result["tools_registered"][0]["registered"] is True
    assert factory.metrics["successes"] == 1
    assert factory.metrics["repair_attempts"] == 0


# ---------------------------------------------------------------------------
# Cross-run persistence: tools registered in run A must be available in run B
# of the same experiment.
# ---------------------------------------------------------------------------


def _build_factory_for_run(run_dir: Path) -> DynamicToolFactory:
    """Instantiate a factory that mimics the per-run isolation layout.

    Also pre-creates a symlink ``workspace/dynamic_tools -> shared/dynamic_tools``
    so the test exercises the real UI layout where workspace and shared point
    at the same inode.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workspace").mkdir(parents=True, exist_ok=True)
    shared = run_dir.parent.parent / "shared" / "dynamic_tools"
    shared.mkdir(parents=True, exist_ok=True)
    link = run_dir / "workspace" / "dynamic_tools"
    if not link.exists():
        try:
            link.symlink_to(shared.resolve())
        except OSError:
            pass

    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=run_dir, max_timeout=15)
    registry.set_code_executor(executor)
    return DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={
            "enabled": True,
            "allowed_namespaces": ["dyn"],
            "persist": True,
            "dry_run": False,
            "cache": True,
        },
        workflow_dir=run_dir,
        sandbox_type="subprocess",
    )


def test_resolve_shared_dir_per_run_layout(tmp_path: Path):
    """`<exp>/runs/<run_id>` must resolve to `<exp>/shared/dynamic_tools`."""
    exp = tmp_path / "experiment_abc"
    run_dir = exp / "runs" / "run_001"
    run_dir.mkdir(parents=True)
    resolved = DynamicToolFactory._resolve_shared_dir(run_dir)
    assert resolved == (exp / "shared" / "dynamic_tools").resolve()


def test_resolve_shared_dir_legacy_flat(tmp_path: Path):
    exp = tmp_path / "experiment_flat"
    exp.mkdir(parents=True)
    # No sibling shared/ — legacy layout returns None so persistence
    # falls back to workspace-local only.
    assert DynamicToolFactory._resolve_shared_dir(exp) is None


def test_tool_registered_in_run_a_is_loaded_by_run_b(tmp_path: Path):
    """End-to-end: create a tool in run A, then a fresh factory in run B
    (same experiment) must auto-load it."""
    exp = tmp_path / "experiment_crossrun"

    # --- Run A: create and register a tool ---
    run_a = exp / "runs" / "run_A"
    fa = _build_factory_for_run(run_a)
    code = (
        "def handler(*, x):\n"
        "    return {'ok': True, 'status': 200, 'data': {'doubled': x*2}, 'error': None}\n"
    )
    params = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    res = fa.create_tool(
        name="dyn.doubler",
        description="double an int",
        parameters=params,
        code=code,
        creator_agent="agent_A",
        allowed_namespace="dyn",
    )
    assert res["ok"], res
    # The shared file must now exist at the experiment-level path
    shared_file = exp / "shared" / "dynamic_tools" / "dyn.doubler.json"
    assert shared_file.exists(), (
        f"Tool was not persisted to shared/ (layout broken). "
        f"Listing: {list((exp / 'shared' / 'dynamic_tools').iterdir()) if (exp / 'shared').exists() else 'no shared dir'}"
    )

    # --- Run B: fresh factory under the same experiment ---
    run_b = exp / "runs" / "run_B"
    fb = _build_factory_for_run(run_b)
    # Run B's registry must expose the tool without the worker re-creating it.
    assert "dyn.doubler" in fb._registry._tools, (
        f"Cross-run load failed. Registry: {list(fb._registry._tools.keys())}"
    )
    # Metadata preserved (creator, code_hash)
    rec_b = fb._records["dyn.doubler"]
    assert rec_b.creator_agent == "agent_A"
    assert rec_b.code_hash  # not empty


def test_persist_survives_broken_symlink(tmp_path: Path):
    """If the workspace symlink is missing, the shared/ write must still
    succeed so tools don't vanish."""
    exp = tmp_path / "experiment_broken_link"
    run_dir = exp / "runs" / "run_X"
    run_dir.mkdir(parents=True)
    (run_dir / "workspace").mkdir()  # no dynamic_tools symlink

    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=run_dir, max_timeout=15)
    registry.set_code_executor(executor)
    factory = DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={"enabled": True, "allowed_namespaces": ["dyn"], "persist": True, "dry_run": False},
        workflow_dir=run_dir,
    )
    res = factory.create_tool(
        name="dyn.noop",
        description="noop",
        parameters={"type": "object", "properties": {}},
        code="def handler(**_):\n    return {'ok': True, 'status': 200, 'data': {}, 'error': None}\n",
        creator_agent="a",
        allowed_namespace="dyn",
    )
    assert res["ok"], res
    # Shared copy must exist even without a pre-existing symlink.
    assert (exp / "shared" / "dynamic_tools" / "dyn.noop.json").exists()


def test_dry_run_handles_unicode(factory: DynamicToolFactory):
    code = textwrap.dedent("""\
        def handler(*, name):
            greeting = f"Hallo {name} 👋"
            return {"ok": True, "status": 200, "data": {"greeting": greeting}, "error": None}
    """)
    params = {"type": "object", "properties": {"name": {"type": "string"}}}
    r = factory.create_tool("dyn.unicode", "x", params, code, "a", allowed_namespace="dyn")
    assert r["ok"], r.get("error")
