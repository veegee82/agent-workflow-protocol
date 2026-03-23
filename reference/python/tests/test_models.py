"""Test AWP data models."""

import pytest

from awp.models import AWPManifest
from awp.models.agent import AWPAgent, OutputField, OutputConfig
from awp.models.common import (
    _validate_semver,
    _validate_agent_id,
    _validate_tool_fqn,
    _validate_workflow_name,
    RESERVED_TOOL_NAMESPACES,
)
from awp.models.orchestration import AWPOrchestrationConfig, GraphNode
from awp.models.communication import CommunicationConfig, MessageEnvelope
from awp.models.memory import MemoryConfig
from awp.models.observability import ObservabilityConfig
from awp.models.security import SecurityConfig
from awp.models.capabilities import AgentCapabilities, ToolsCapability
from awp.models.custom_tools import CustomToolsConfig


# -- Common validators -----------------------------------------------

class TestSemVer:
    def test_valid(self):
        assert _validate_semver("1.0.0") == "1.0.0"
        assert _validate_semver("0.1.0-alpha") == "0.1.0-alpha"
        assert _validate_semver("2.3.4+build.123") == "2.3.4+build.123"

    def test_invalid(self):
        with pytest.raises(ValueError):
            _validate_semver("not-a-version")
        with pytest.raises(ValueError):
            _validate_semver("1.0")
        with pytest.raises(ValueError):
            _validate_semver("")


class TestAgentId:
    def test_valid(self):
        assert _validate_agent_id("researcher") == "researcher"
        assert _validate_agent_id("my_agent_01") == "my_agent_01"
        assert _validate_agent_id("a") == "a"

    def test_invalid(self):
        with pytest.raises(ValueError):
            _validate_agent_id("Agent")  # uppercase
        with pytest.raises(ValueError):
            _validate_agent_id("my-agent")  # hyphen
        with pytest.raises(ValueError):
            _validate_agent_id("1agent")  # starts with digit


class TestToolFQN:
    def test_valid(self):
        assert _validate_tool_fqn("web.search") == "web.search"
        assert _validate_tool_fqn("file.read") == "file.read"

    def test_invalid(self):
        with pytest.raises(ValueError):
            _validate_tool_fqn("nodot")
        with pytest.raises(ValueError):
            _validate_tool_fqn("Web.Search")  # uppercase


class TestWorkflowName:
    def test_valid(self):
        assert _validate_workflow_name("hello-world") == "hello-world"
        assert _validate_workflow_name("my_workflow") == "my_workflow"
        assert _validate_workflow_name("a") == "a"

    def test_invalid(self):
        with pytest.raises(ValueError):
            _validate_workflow_name("01-hello")  # starts with digit
        with pytest.raises(ValueError):
            _validate_workflow_name("Hello")  # uppercase


# -- Manifest --------------------------------------------------------

class TestManifest:
    def test_minimal(self):
        m = AWPManifest(
            awp="1.0.0",
            workflow={
                "name": "test-wf",
                "version": "1.0.0",
                "description": "Test workflow",
            },
        )
        assert m.workflow.name == "test-wf"
        assert m.workflow.version == "1.0.0"
        assert m.orchestration is None

    def test_with_orchestration(self):
        m = AWPManifest(
            awp="1.0.0",
            workflow={
                "name": "test-wf",
                "version": "1.0.0",
                "description": "Test",
            },
            orchestration=AWPOrchestrationConfig(
                graph=[GraphNode(id="agent_a", agent="agent_a")],
            ),
        )
        assert len(m.orchestration.graph) == 1
        assert m.orchestration.graph[0].id == "agent_a"


# -- Agent -----------------------------------------------------------

class TestAgent:
    def test_minimal(self):
        a = AWPAgent(
            awp_agent="1.0.0",
            identity={"id": "researcher", "role": "investigator", "description": "Researches"},
            model={"name": "provider/model"},
            prompt={"system": "instructions/SYSTEM_PROMPT.md"},
            output={"format": "json", "contract": {
                "result": {"type": "string", "required": True},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0, "required": True},
            }},
        )
        assert a.identity.id == "researcher"
        assert a.model.name == "provider/model"
        assert "confidence" in a.output.contract

    def test_output_field(self):
        f = OutputField(type="string", description="test", shareable=True, required=True)
        assert f.shareable is True
        assert f.sensitive is False


# -- Orchestration ---------------------------------------------------

class TestOrchestration:
    def test_graph_node(self):
        n = GraphNode(id="planner", agent="planner", depends_on=[], description="Plans")
        assert n.id == "planner"
        assert n.enabled is True
        assert n.on_failure == "continue"

    def test_execution_defaults(self):
        orch = AWPOrchestrationConfig()
        assert orch.engine == "dag"
        assert orch.execution.mode == "parallel"
        assert orch.execution.timeout.per_agent == 120


# -- Capabilities ----------------------------------------------------

class TestCapabilities:
    def test_tools_default(self):
        t = ToolsCapability()
        assert t.enabled is False
        assert t.max_calls == 0

    def test_capabilities(self):
        c = AgentCapabilities(
            tools=ToolsCapability(enabled=True, max_calls=10, allowed=["web.search"]),
        )
        assert c.tools.enabled is True
        assert "web.search" in c.tools.allowed


# -- Communication ---------------------------------------------------

class TestCommunication:
    def test_defaults(self):
        c = CommunicationConfig()
        assert c.bus.type == "internal"
        assert c.default_channel == "direct"


# -- Memory ----------------------------------------------------------

class TestMemory:
    def test_defaults(self):
        m = MemoryConfig()
        assert m.enabled is True
        assert m.long_term.enabled is True
        assert m.daily_log.enabled is True
        assert m.semantic.enabled is False


# -- Observability ---------------------------------------------------

class TestObservability:
    def test_defaults(self):
        o = ObservabilityConfig()
        assert o.metrics.enabled is False
        assert o.tracing.enabled is False
        assert o.audit.enabled is False


# -- Security --------------------------------------------------------

class TestSecurity:
    def test_defaults(self):
        s = SecurityConfig()
        assert s.circuit_breaker.enabled is False
        assert s.rate_limit.enabled is False
        assert s.secrets_backend == "env"


# -- Reserved namespaces ---------------------------------------------

class TestReservedNamespaces:
    def test_builtins(self):
        assert "web" in RESERVED_TOOL_NAMESPACES
        assert "shell" in RESERVED_TOOL_NAMESPACES
        assert "memory" in RESERVED_TOOL_NAMESPACES
        assert "custom" not in RESERVED_TOOL_NAMESPACES
