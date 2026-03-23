"""Tests for AWP standalone runtime -- tools, LLM client, agent capabilities."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from awp.runtime.llm import LLMClient, _detect_provider, _find_api_key, PROVIDER_URLS
from awp.runtime.tools import ToolRegistry
from awp.runtime.agent import StandaloneAgent
from awp.runtime.runner import WorkflowRunner

EXAMPLES = Path(__file__).parents[3] / "examples"


# -- Provider detection -----------------------------------------------

class TestProviderDetection:
    def test_detect_from_model_prefix(self):
        assert _detect_provider("openai/gpt-4o") == "openai"
        assert _detect_provider("openrouter/model") == "openrouter"
        assert _detect_provider("ollama/llama3") == "ollama"
        assert _detect_provider("groq/llama-3.1") == "groq"
        assert _detect_provider("together/model") == "together"
        assert _detect_provider("mistral/model") == "mistral"
        assert _detect_provider("deepseek/model") == "deepseek"

    def test_no_prefix(self):
        assert _detect_provider("gpt-4o") is None
        assert _detect_provider("llama3") is None

    def test_known_providers_have_urls(self):
        for provider in PROVIDER_URLS:
            assert PROVIDER_URLS[provider].startswith("http")


class TestLLMClient:
    def test_init_with_explicit_params(self):
        client = LLMClient(
            api_key="test-key",
            base_url="http://localhost:8080/v1",
            model="test-model",
        )
        assert client.api_key == "test-key"
        assert client.base_url == "http://localhost:8080/v1"
        assert client.model == "test-model"

    def test_ollama_no_key_needed(self):
        client = LLMClient(
            base_url="http://localhost:11434/v1",
            model="llama3",
        )
        assert client.api_key == "ollama"

    def test_auto_detect_from_model(self):
        client = LLMClient(model="openai/gpt-4o", api_key="sk-test")
        assert "openai" in client.base_url

    def test_missing_model_raises(self):
        client = LLMClient(api_key="test", base_url="http://localhost:8080/v1")
        with pytest.raises(RuntimeError, match="No model configured"):
            client.chat([{"role": "user", "content": "test"}])


# -- Tool registry ----------------------------------------------------

class TestToolRegistry:
    def test_builtin_tools_registered(self):
        reg = ToolRegistry()
        names = reg.tool_names
        assert "file.read" in names
        assert "file.write" in names
        assert "file.list" in names
        assert "shell.execute" in names
        assert "arithmetic.add" in names
        assert "arithmetic.subtract" in names
        assert "arithmetic.multiply" in names
        assert "arithmetic.divide" in names
        assert "memory.read" in names
        assert "memory.write" in names
        assert "memory.search" in names

    def test_file_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            f.flush()
            reg = ToolRegistry()
            result = reg.call("file.read", {"path": f.name})
            assert result["ok"] is True
            assert result["data"]["content"] == "hello world"
            os.unlink(f.name)

    def test_file_read_not_found(self):
        reg = ToolRegistry()
        result = reg.call("file.read", {"path": "/nonexistent/file.txt"})
        assert result["ok"] is False
        assert result["status"] == 404

    def test_file_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = ToolRegistry()
            path = str(Path(tmp) / "test.txt")
            w = reg.call("file.write", {"path": path, "content": "test content"})
            assert w["ok"] is True

            r = reg.call("file.read", {"path": path})
            assert r["ok"] is True
            assert r["data"]["content"] == "test content"

    def test_file_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("a")
            Path(tmp, "b.txt").write_text("b")
            reg = ToolRegistry()
            result = reg.call("file.list", {"path": tmp})
            assert result["ok"] is True
            assert result["data"]["count"] == 2

    def test_shell_execute(self):
        reg = ToolRegistry()
        result = reg.call("shell.execute", {"command": "echo hello"})
        assert result["ok"] is True
        assert "hello" in result["data"]["stdout"]

    def test_shell_timeout(self):
        reg = ToolRegistry()
        result = reg.call("shell.execute", {"command": "sleep 10", "timeout": 1})
        assert result["ok"] is False
        assert result["status"] == 408

    def test_arithmetic(self):
        reg = ToolRegistry()
        assert reg.call("arithmetic.add", {"a": 3, "b": 4})["data"]["result"] == 7
        assert reg.call("arithmetic.subtract", {"a": 10, "b": 3})["data"]["result"] == 7
        assert reg.call("arithmetic.multiply", {"a": 3, "b": 4})["data"]["result"] == 12
        assert reg.call("arithmetic.divide", {"a": 10, "b": 2})["data"]["result"] == 5.0

    def test_divide_by_zero(self):
        reg = ToolRegistry()
        result = reg.call("arithmetic.divide", {"a": 10, "b": 0})
        assert result["ok"] is False

    def test_unknown_tool(self):
        reg = ToolRegistry()
        result = reg.call("nonexistent.tool", {})
        assert result["ok"] is False
        assert result["status"] == 404

    def test_memory_read_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf_dir = Path(tmp)
            reg = ToolRegistry(wf_dir)

            # Write to daily log
            w = reg.call("memory.write", {"content": "Test entry", "target": "daily"})
            assert w["ok"] is True

            # Read daily log
            r = reg.call("memory.read", {"target": "daily"})
            assert r["ok"] is True
            assert "Test entry" in r["data"]["content"]

            # Write to long-term
            w2 = reg.call("memory.write", {"content": "Long-term fact", "target": "long_term"})
            assert w2["ok"] is True

            # Read long-term
            r2 = reg.call("memory.read", {"target": "long_term"})
            assert r2["ok"] is True
            assert "Long-term fact" in r2["data"]["content"]

            # Search
            s = reg.call("memory.search", {"query": "fact"})
            assert s["ok"] is True
            assert len(s["data"]["results"]) > 0

            # List dates
            d = reg.call("memory.read", {"target": "dates"})
            assert d["ok"] is True
            assert len(d["data"]["dates"]) == 1

    def test_get_definitions(self):
        reg = ToolRegistry()
        all_defs = reg.get_definitions()
        assert len(all_defs) >= 11

        # Filter by pattern
        file_defs = reg.get_definitions(["file.*"])
        assert all("file." in d["function"]["name"] for d in file_defs)
        assert len(file_defs) == 3

        # Filter by exact name
        exact = reg.get_definitions(["arithmetic.add"])
        assert len(exact) == 1

    def test_custom_tool_discovery(self):
        """Test that custom tools from mcp/ directory are discovered."""
        with tempfile.TemporaryDirectory() as tmp:
            mcp_dir = Path(tmp) / "mcp"
            mcp_dir.mkdir()

            # Create a custom tool file
            tool_file = mcp_dir / "custom_tools.py"
            tool_file.write_text('''
try:
    from mcp.server.fastmcp import FastMCP
except Exception:
    class FastMCP:
        def __init__(self, name): self.name = name
        def tool(self, _name):
            def _d(fn): return fn
            return _d

app = FastMCP("custom")

@app.tool("custom.greet")
def greet(*, name: str) -> dict:
    """Say hello to someone."""
    return {"ok": True, "status": 200, "data": {"greeting": f"Hello {name}"}, "error": None}
''')

            reg = ToolRegistry(Path(tmp))
            assert "custom.greet" in reg.tool_names
            result = reg.call("custom.greet", {"name": "World"})
            assert result["ok"] is True
            assert result["data"]["greeting"] == "Hello World"


# -- StandaloneAgent with tools --------------------------------------

class TestStandaloneAgentCapabilities:
    def test_skills_loading(self):
        """Test that project-level skills are loaded."""
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp)
            # Create minimal workflow
            (wf / "workflow.awp.yaml").write_text(
                'awp: "1.0.0"\nworkflow:\n  name: test\n  version: "1.0.0"\n  description: test\n'
            )
            # Create agent
            agent_dir = wf / "agents" / "tester"
            agent_dir.mkdir(parents=True)
            (agent_dir / "agent.awp.yaml").write_text(
                'awp_agent: "1.0.0"\n'
                'identity:\n  id: tester\n  role: test\n  description: test\n'
                'model:\n  name: test/model\n'
                'prompt:\n  system: instructions/SYSTEM_PROMPT.md\n'
                'output:\n  format: json\n  contract:\n'
                '    result:\n      type: string\n      required: true\n'
                '    confidence:\n      type: number\n      minimum: 0.0\n      maximum: 1.0\n      required: true\n'
            )
            instr = agent_dir / "workflow" / "instructions"
            instr.mkdir(parents=True)
            (instr / "SYSTEM_PROMPT.md").write_text("You are a tester.")

            # Create project-level skill
            skill_dir = wf / "skills" / "test_knowledge"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# Test Knowledge\n\nThis is domain knowledge.")

            agent = StandaloneAgent(agent_dir, wf)
            prompt = agent._build_system_prompt()
            assert "You are a tester" in prompt
            assert "Test Knowledge" in prompt
            assert "domain knowledge" in prompt

    def test_memory_injection(self):
        """Test that MEMORY.md is injected into system prompt."""
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp)
            (wf / "workflow.awp.yaml").write_text(
                'awp: "1.0.0"\nworkflow:\n  name: test\n  version: "1.0.0"\n  description: test\n'
                'memory:\n  enabled: true\n  long_term:\n    enabled: true\n    inject: true\n'
            )
            agent_dir = wf / "agents" / "tester"
            agent_dir.mkdir(parents=True)
            (agent_dir / "agent.awp.yaml").write_text(
                'awp_agent: "1.0.0"\n'
                'identity:\n  id: tester\n  role: test\n  description: test\n'
                'model:\n  name: test/model\n'
                'prompt:\n  system: instructions/SYSTEM_PROMPT.md\n'
                'output:\n  format: json\n  contract:\n'
                '    confidence:\n      type: number\n      minimum: 0.0\n      maximum: 1.0\n      required: true\n'
            )
            instr = agent_dir / "workflow" / "instructions"
            instr.mkdir(parents=True)
            (instr / "SYSTEM_PROMPT.md").write_text("You are a tester.")

            # Create MEMORY.md
            ws = wf / "workspace"
            ws.mkdir()
            (ws / "MEMORY.md").write_text("User prefers detailed explanations.")

            agent = StandaloneAgent(agent_dir, wf)
            prompt = agent._build_system_prompt()
            assert "Long-term Memory" in prompt
            assert "detailed explanations" in prompt
