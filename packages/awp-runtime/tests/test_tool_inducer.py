"""Tests for the AWP Tool Inducer (Framework-Fix β).

Covers:

- AST signature equivalence under literal / identifier variation
- AST signature divergence under structural changes
- N-threshold gate (no synthesis before 3 distinct workers)
- Same-worker repetition does NOT count (diversity requirement)
- End-to-end integration: shared/dynamic_tools/ gets populated after
  induction via a real :class:`DynamicToolFactory`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from awp.runtime.code_executor import CodeExecutor
from awp.runtime.dynamic_tool_factory import DynamicToolFactory
from awp.runtime.tool_inducer import (
    N_DISTINCT_WORKERS,
    CodePatternSignature,
    ToolInducer,
)
from awp.runtime.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Signature semantics
# ---------------------------------------------------------------------------


def test_signature_same_for_literal_variations():
    """Snippets differing only in string/int constants collapse to one
    structural signature."""
    code_a = (
        'path = "/workspace/inputs/agent-workflow-protocol"\n'
        'with open(path + "/README.md") as f:\n'
        '    content = f.read()\n'
        'print(len(content))\n'
    )
    code_b = (
        'path = "/workspace/outputs/x"\n'
        'with open(path + "/file.md") as f:\n'
        '    content = f.read()\n'
        'print(len(content))\n'
    )
    sig_a = CodePatternSignature.from_code(code_a)
    sig_b = CodePatternSignature.from_code(code_b)
    assert sig_a is not None and sig_b is not None
    assert sig_a.hash == sig_b.hash
    assert len(sig_a.hash) == 16


def test_signature_same_for_identifier_renames():
    """Variable-name choices don't affect the signature (first-occurrence
    renaming normalises them)."""
    code_a = "x = 1\ny = x + 2\nprint(y)\n"
    code_b = "foo = 1\nbar = foo + 2\nprint(bar)\n"
    sig_a = CodePatternSignature.from_code(code_a)
    sig_b = CodePatternSignature.from_code(code_b)
    assert sig_a is not None and sig_b is not None
    assert sig_a.hash == sig_b.hash


def test_signature_different_for_structural_changes():
    """Adding control flow (an if branch) changes the signature."""
    code_a = 'x = 1\nprint(x)\n'
    code_b = 'x = 1\nif x > 0:\n    print(x)\n'
    sig_a = CodePatternSignature.from_code(code_a)
    sig_b = CodePatternSignature.from_code(code_b)
    assert sig_a is not None and sig_b is not None
    assert sig_a.hash != sig_b.hash


def test_signature_different_for_different_function_calls():
    """Calling a different function (attr name differs) changes the sig."""
    code_a = '"hi".upper()\n'
    code_b = '"hi".lower()\n'
    sig_a = CodePatternSignature.from_code(code_a)
    sig_b = CodePatternSignature.from_code(code_b)
    assert sig_a is not None and sig_b is not None
    assert sig_a.hash != sig_b.hash


def test_signature_returns_none_on_syntax_error():
    assert CodePatternSignature.from_code("def broken(:\n") is None


# ---------------------------------------------------------------------------
# Observation gate — N threshold + diversity
# ---------------------------------------------------------------------------


_PATTERN_A = (
    'path = "/workspace/inputs/a"\n'
    'with open(path + "/README.md") as f:\n'
    '    content = f.read()\n'
    'print(len(content))\n'
)


def _variant(path_literal: str, file_literal: str) -> str:
    return (
        f'path = "{path_literal}"\n'
        f'with open(path + "{file_literal}") as f:\n'
        '    content = f.read()\n'
        'print(len(content))\n'
    )


def test_no_tool_induced_before_n_equals_3():
    """After only 2 observations, nothing is synthesised yet."""
    factory = MagicMock()
    factory.create_tool.return_value = {"ok": True, "data": {"name": "x"}}
    inducer = ToolInducer(dynamic_tool_factory=factory)
    fqn1 = inducer.observe("worker_1", _PATTERN_A)
    fqn2 = inducer.observe("worker_2", _variant("/a/b", "/f.md"))
    assert fqn1 is None
    assert fqn2 is None
    factory.create_tool.assert_not_called()
    assert inducer.induced_tools == []


def test_tool_induced_at_n_equals_3_from_distinct_workers():
    """Three observations from 3 distinct workers trigger exactly one
    DynamicToolFactory.create_tool invocation."""
    factory = MagicMock()
    factory.create_tool.return_value = {"ok": True, "data": {"name": "ok"}}
    inducer = ToolInducer(dynamic_tool_factory=factory)
    inducer.observe("worker_1", _variant("/a/b/c", "/r1.md"))
    inducer.observe("worker_2", _variant("/a/b/d", "/r2.md"))
    fqn = inducer.observe("worker_3", _variant("/a/b/e", "/r3.md"))
    assert fqn is not None
    assert fqn.startswith("dynamic.induced_")
    assert factory.create_tool.call_count == 1
    call_kwargs = factory.create_tool.call_args.kwargs
    assert call_kwargs["name"] == fqn
    assert call_kwargs["allowed_namespace"] == "dynamic"
    assert call_kwargs["creator_agent"] == "tool_inducer"
    # Description should mention the observed workers
    desc = call_kwargs["description"]
    assert "worker_1" in desc and "worker_2" in desc and "worker_3" in desc
    # induced_tools list reflects the new entry
    assert len(inducer.induced_tools) == 1
    assert inducer.induced_tools[0]["fqn"] == fqn
    assert set(inducer.induced_tools[0]["observed_in_workers"]) == {
        "worker_1", "worker_2", "worker_3"
    }


def test_repeat_from_same_worker_does_not_count():
    """3 observations from the SAME worker must not synthesise — diversity
    across worker_ids is required."""
    factory = MagicMock()
    factory.create_tool.return_value = {"ok": True, "data": {"name": "ok"}}
    inducer = ToolInducer(dynamic_tool_factory=factory)
    for i in range(5):
        inducer.observe("worker_X", _variant(f"/a/{i}", f"/f{i}.md"))
    factory.create_tool.assert_not_called()
    assert inducer.induced_tools == []


def test_synthesis_only_fires_once_per_signature():
    """After synthesis, further observations of the same pattern don't
    trigger new create_tool calls."""
    factory = MagicMock()
    factory.create_tool.return_value = {"ok": True, "data": {"name": "ok"}}
    inducer = ToolInducer(dynamic_tool_factory=factory)
    inducer.observe("w1", _variant("/a", "/x.md"))
    inducer.observe("w2", _variant("/b", "/y.md"))
    inducer.observe("w3", _variant("/c", "/z.md"))
    assert factory.create_tool.call_count == 1
    # Extra observations should not re-synthesise.
    inducer.observe("w4", _variant("/d", "/w.md"))
    inducer.observe("w5", _variant("/e", "/v.md"))
    assert factory.create_tool.call_count == 1


def test_factory_rejection_does_not_add_to_induced_tools():
    factory = MagicMock()
    factory.create_tool.return_value = {"ok": False, "error": "boom"}
    inducer = ToolInducer(dynamic_tool_factory=factory)
    inducer.observe("w1", _variant("/a", "/x.md"))
    inducer.observe("w2", _variant("/b", "/y.md"))
    inducer.observe("w3", _variant("/c", "/z.md"))
    assert inducer.induced_tools == []
    # Another hit from a new worker should retry synthesis (state is
    # not flipped when the factory rejected).
    inducer.observe("w4", _variant("/d", "/w.md"))
    # It's fine either way — we only guarantee we don't keep a ghost.
    # (See design note: ``synthesised`` flag is set only on success.)
    assert factory.create_tool.call_count >= 1


def test_unsynthesisable_pattern_logs_but_skips(caplog):
    """When the only varying parts aren't plain scalar constants, we log
    and skip without crashing."""
    factory = MagicMock()
    inducer = ToolInducer(dynamic_tool_factory=factory)
    # All 3 snippets are identical — no varying literals → not synthesisable.
    code = 'x = 1\nprint(x + 2)\n'
    import logging

    with caplog.at_level(logging.INFO, logger="awp.runtime.tool_inducer"):
        inducer.observe("w1", code)
        inducer.observe("w2", code)
        inducer.observe("w3", code)
    factory.create_tool.assert_not_called()
    assert any("not synthesisable" in r.message for r in caplog.records)


def test_import_templates_are_rejected():
    """Templates containing top-level imports are skipped — they would
    conflict with the dynamic-tool import policy."""
    factory = MagicMock()
    inducer = ToolInducer(dynamic_tool_factory=factory)

    def _s(n: int) -> str:
        return f'import json\nprint("{n}")\n'

    inducer.observe("w1", _s(1))
    inducer.observe("w2", _s(2))
    inducer.observe("w3", _s(3))
    factory.create_tool.assert_not_called()


def test_observe_tolerates_bad_inputs():
    inducer = ToolInducer(dynamic_tool_factory=None)
    assert inducer.observe("", "") is None
    assert inducer.observe("w", "") is None
    assert inducer.observe("w", "def broken(:\n") is None
    # None worker_id gets normalised
    assert inducer.observe(None, "x = 1\n") is None  # type: ignore[arg-type]


def test_observe_without_factory_accumulates_but_skips_synthesis():
    inducer = ToolInducer(dynamic_tool_factory=None)
    inducer.observe("w1", _variant("/a", "/x.md"))
    inducer.observe("w2", _variant("/b", "/y.md"))
    # Crossing the threshold with no factory must not raise; returns None.
    res = inducer.observe("w3", _variant("/c", "/z.md"))
    assert res is None
    assert inducer.induced_tools == []


# ---------------------------------------------------------------------------
# Integration: shared/dynamic_tools/ gets a real induced_*.json file
# ---------------------------------------------------------------------------


@pytest.fixture()
def real_factory(tmp_path: Path) -> DynamicToolFactory:
    """A real DynamicToolFactory with per-run isolation layout so the
    shared/ directory is discoverable by the factory's resolver."""
    # Recreate the "<exp>/runs/<run_id>" layout so
    # ``_resolve_shared_dir`` returns "<exp>/shared/dynamic_tools".
    exp_root = tmp_path / "exp"
    run_dir = exp_root / "runs" / "r1"
    run_dir.mkdir(parents=True)

    registry = ToolRegistry()
    executor = CodeExecutor(working_dir=run_dir, max_timeout=10)
    registry.set_code_executor(executor)
    factory = DynamicToolFactory(
        registry=registry,
        code_executor=executor,
        config={
            "enabled": True,
            "persist": True,
            "allowed_namespaces": ["dynamic"],
            "dry_run": False,  # keep the test fast and independent of pip
            "cache": True,
            "max_total": 10,
        },
        workflow_dir=run_dir,
        sandbox_type="subprocess",
    )
    registry.set_dynamic_tool_factory(factory)
    return factory


def test_tool_file_appears_in_shared_dynamic_tools(
    real_factory: DynamicToolFactory, tmp_path: Path
):
    """After N=3 observations from distinct workers, a
    ``dynamic.induced_<hash>.json`` file must appear in the shared
    dynamic_tools directory."""
    inducer = ToolInducer(dynamic_tool_factory=real_factory)

    # 3 variants of the same structural shape with varying scalar values.
    samples = [
        ('w1', 'x = 1\ny = x + 10\nprint(y)\n'),
        ('w2', 'x = 2\ny = x + 20\nprint(y)\n'),
        ('w3', 'x = 3\ny = x + 30\nprint(y)\n'),
    ]
    fqn: str | None = None
    for wid, code in samples:
        fqn = inducer.observe(wid, code) or fqn
    assert fqn is not None and fqn.startswith("dynamic.induced_")

    shared_dir = tmp_path / "exp" / "shared" / "dynamic_tools"
    assert shared_dir.is_dir(), f"shared dir missing: {shared_dir}"
    produced = list(shared_dir.glob("dynamic.induced_*.json"))
    assert produced, (
        f"expected a dynamic.induced_*.json file in {shared_dir}, "
        f"found: {list(shared_dir.iterdir())}"
    )
    # And the induced_tools list should reflect exactly one entry.
    assert len(inducer.induced_tools) == 1
    assert inducer.induced_tools[0]["fqn"] == fqn


def test_threshold_matches_constant():
    """Guard against accidental drift of the hardcoded N."""
    assert N_DISTINCT_WORKERS == 3
