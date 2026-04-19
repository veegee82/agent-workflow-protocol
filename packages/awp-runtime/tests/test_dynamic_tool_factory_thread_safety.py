"""Thread-safety tests for the dynamic tool factory.

Covers two invariants under parallel ``create_tool`` calls:

* Every in-memory record ends up registered exactly once and the
  per-agent / per-hash indices stay consistent.
* Every on-disk JSON manifest is fully written (no half-finished
  files) thanks to the atomic temp-file + ``os.replace`` pattern in
  ``_persist_tool``.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from awp.runtime.code_executor import CodeExecutor
from awp.runtime.dynamic_tool_factory import DynamicToolFactory
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
            "dry_run": False,
            "cache": True,
            "persist": True,
            "max_total": 200,
            "timeout_seconds": 8,
        },
        workflow_dir=tmp_path,
        sandbox_type="subprocess",
    )


def _tool_code(marker: int) -> str:
    return (
        "def handler(*, value):\n"
        f"    return {{'ok': True, 'status': 200, 'data': {{'marker': {marker}, 'value': value}}, 'error': None, 'log': ''}}\n"
    )


def test_parallel_create_tool_registers_all_unique_tools(
    factory: DynamicToolFactory,
    tmp_path: Path,
) -> None:
    num_tools = 50
    results: list[dict] = [None] * num_tools  # type: ignore[list-item]
    errors: list[BaseException] = []
    barrier = threading.Barrier(num_tools)

    def worker(idx: int) -> None:
        try:
            barrier.wait(timeout=10)
            name = f"dyn.tool_{idx:03d}"
            result = factory.create_tool(
                name=name,
                description=f"Tool {idx}",
                parameters={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
                code=_tool_code(idx),
                creator_agent=f"agent_{idx % 5}",
                max_tools=50,
                allowed_namespace="dyn",
            )
            results[idx] = result
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_tools)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"workers raised: {errors}"
    ok = [r for r in results if r and r.get("ok")]
    assert len(ok) == num_tools, f"only {len(ok)}/{num_tools} tools registered"

    assert len(factory._records) == num_tools
    for i in range(num_tools):
        assert f"dyn.tool_{i:03d}" in factory._records

    total_agent_count = sum(factory._agent_counts.values())
    assert total_agent_count == num_tools

    assert len(factory._hash_to_fqn) == num_tools


def test_parallel_create_tool_writes_valid_json_files(
    factory: DynamicToolFactory,
    tmp_path: Path,
) -> None:
    num_tools = 50
    barrier = threading.Barrier(num_tools)

    def worker(idx: int) -> None:
        barrier.wait(timeout=10)
        factory.create_tool(
            name=f"dyn.disk_{idx:03d}",
            description=f"Disk tool {idx}",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            code=_tool_code(1000 + idx),
            creator_agent=f"agent_{idx % 3}",
            max_tools=50,
            allowed_namespace="dyn",
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_tools)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    persist_dir = tmp_path / "workspace" / "dynamic_tools"
    assert persist_dir.exists(), "persist dir not created"

    json_files = sorted(persist_dir.glob("dyn.disk_*.json"))
    assert len(json_files) == num_tools

    for path in json_files:
        # No leftover temp files.
        assert not path.name.startswith("."), f"temp file leaked: {path}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["fqn"].startswith("dyn.disk_")
        assert "code" in data and "def handler" in data["code"]
        assert data["parameters"]["type"] == "object"

    # No stray .tmp files in the persist dir.
    leftovers = [p for p in persist_dir.iterdir() if p.name.startswith(".")]
    assert not leftovers, f"temp files not cleaned up: {leftovers}"


def test_parallel_create_same_tool_deduplicates(factory: DynamicToolFactory) -> None:
    num_threads = 20
    results: list[dict] = [None] * num_threads  # type: ignore[list-item]
    barrier = threading.Barrier(num_threads)

    code = _tool_code(42)
    params = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    }

    def worker(idx: int) -> None:
        barrier.wait(timeout=10)
        results[idx] = factory.create_tool(
            name="dyn.shared",
            description="Shared tool",
            parameters=params,
            code=code,
            creator_agent="agent_shared",
            max_tools=5,
            allowed_namespace="dyn",
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one winner; the rest are cache hits or duplicate-name rejections.
    assert "dyn.shared" in factory._records
    assert len(factory._records) == 1

    ok_results = [r for r in results if r and r.get("ok")]
    assert len(ok_results) >= 1
