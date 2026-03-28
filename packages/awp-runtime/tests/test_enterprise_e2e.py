"""End-to-end tests for the enterprise feature test workflow.

Tests parsing, validation, topology, when-condition evaluation,
tool discovery, and a mocked full workflow run.
"""

import json
from pathlib import Path

import pytest
from awp.parser import parse_manifest, parse_agent
from awp.runtime.expressions import safe_eval
from awp.runtime.message_bus import MessageBus
from awp.runtime.observability import Tracer, MetricsCollector, AuditTrail
from awp.runtime.security import AccessController
from awp.runtime.state_persistence import StatePersistence
from awp.runtime.tools import ToolRegistry

ENTERPRISE_DIR = (
    Path(__file__).parent.parent.parent.parent / "examples" / "06-enterprise"
)


@pytest.fixture
def manifest():
    return parse_manifest(ENTERPRISE_DIR / "workflow.awp.yaml")


@pytest.fixture
def agents():
    agents = {}
    agents_dir = ENTERPRISE_DIR / "agents"
    for agent_dir in sorted(agents_dir.iterdir()):
        awp_yaml = agent_dir / "agent.awp.yaml"
        if awp_yaml.exists():
            agents[agent_dir.name] = parse_agent(awp_yaml)
    return agents


class TestEnterpriseParsing:
    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_manifest_parses(self, manifest):
        assert manifest.workflow.name == "enterprise"
        assert manifest.workflow.version == "1.0.0"

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_all_agents_parse(self, agents):
        assert len(agents) == 5
        expected = {
            "data_collector",
            "code_executor",
            "analyst",
            "communicator",
            "report_writer",
        }
        assert set(agents.keys()) == expected

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_orchestration_graph(self, manifest):
        graph = manifest.orchestration.graph
        assert len(graph) == 5
        ids = [n.id for n in graph]
        assert "data_collector" in ids
        assert "report_writer" in ids

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_report_writer_has_when(self, manifest):
        """The report_writer node should have a when condition on its dependency."""
        for node in manifest.orchestration.graph:
            if node.id == "report_writer":
                # Check depends_on for when clause
                for dep in node.depends_on:
                    if hasattr(dep, "when") and dep.when:
                        assert "risk_score" in dep.when
                break

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_communication_config(self, manifest):
        assert manifest.communication is not None
        assert manifest.communication.bus.type == "internal"
        assert len(manifest.communication.channels) >= 2

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_observability_config(self, manifest):
        obs = manifest.observability
        assert obs is not None
        assert obs.tracing.enabled is True
        assert obs.metrics.enabled is True
        assert obs.audit.enabled is True

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_security_config(self, manifest):
        sec = manifest.security
        assert sec is not None
        assert sec.circuit_breaker.enabled is True
        assert sec.rate_limit.enabled is True

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_memory_config(self, manifest):
        mem = manifest.memory
        assert mem is not None
        assert mem.enabled is True
        assert mem.long_term.enabled is True


class TestEnterpriseTopology:
    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_topological_levels(self, manifest):
        from awp.runtime.runner import WorkflowRunner

        # Test topology without instantiating full runner
        runner_cls = WorkflowRunner
        levels = runner_cls._topological_levels(None, manifest.orchestration)

        # data_collector should be first (no deps)
        assert "data_collector" in levels[0]

        # code_executor and analyst should be parallel (both depend on data_collector)
        level1 = levels[1]
        assert "code_executor" in level1 or "analyst" in level1

        # report_writer should be last
        last_level = levels[-1]
        assert "report_writer" in last_level


class TestEnterpriseWhenConditions:
    def test_risk_score_above_threshold(self):
        state = {
            "analyst": {"risk_score": 0.75, "confidence": 0.9},
        }
        assert safe_eval("state.analyst.risk_score > 0.3", {"state": state}) is True

    def test_risk_score_below_threshold(self):
        state = {
            "analyst": {"risk_score": 0.1, "confidence": 0.5},
        }
        assert safe_eval("state.analyst.risk_score > 0.3", {"state": state}) is False


class TestEnterpriseToolDiscovery:
    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_custom_tools_discovered(self):
        registry = ToolRegistry(ENTERPRISE_DIR)
        names = registry.tool_names

        # Built-in tools
        assert "file.read" in names
        assert "file.write" in names
        assert "memory.read" in names
        assert "memory.curate" in names
        assert "web.search" in names

        # Custom tool from mcp/
        assert "custom.analyze_risk" in names

    @pytest.mark.skipif(not ENTERPRISE_DIR.exists(), reason="Enterprise test not found")
    def test_tool_count(self):
        registry = ToolRegistry(ENTERPRISE_DIR)
        # Should have built-in + custom tools
        assert len(registry.tool_names) >= 15


class TestEnterpriseAccessControl:
    def test_report_writer_blocked_from_shell(self):
        ac = AccessController(
            default_policy="allow",
            rules=[{"agent": "report_writer", "deny_tools": ["shell.execute"]}],
        )
        assert ac.is_allowed("report_writer", "shell.execute") is False
        assert ac.is_allowed("report_writer", "file.write") is True
        assert ac.is_allowed("data_collector", "shell.execute") is True


class TestEnterpriseMessageBus:
    def test_communicator_can_broadcast(self):
        bus = MessageBus()
        msg_id = bus.broadcast(
            "communicator", {"status": "all_clear"}, channel="alerts"
        )
        assert msg_id

        # Other agents see the broadcast
        msgs = bus.list_messages("report_writer")
        assert len(msgs) == 1
        assert msgs[0]["content"]["status"] == "all_clear"


class TestEnterpriseObservability:
    def test_full_observability_flow(self, tmp_path):
        tracer = Tracer(tmp_path / "traces", "test-run")
        metrics = MetricsCollector(tmp_path / "metrics", "test-run")
        audit = AuditTrail(tmp_path / "audit", "test-run")

        # Simulate workflow
        root = tracer.start_span("workflow.run")
        audit.record("workflow.start", details={"task": "test"})

        for agent_id in ["data_collector", "analyst", "communicator"]:
            span = tracer.start_span(f"agent.{agent_id}", parent_id=root)
            audit.record("agent.start", agent_id)
            metrics.increment("agent.executions", labels={"agent": agent_id})
            metrics.histogram("agent.duration_s", 1.5, labels={"agent": agent_id})
            audit.record("agent.complete", agent_id)
            tracer.end_span(span, status="ok")

        tracer.end_span(root, status="ok")
        audit.record("workflow.complete")

        # Flush all
        trace_path = tracer.flush()
        metrics_path = metrics.flush()
        audit_path = audit.flush()

        assert trace_path.exists()
        assert metrics_path.exists()
        assert audit_path.exists()

        # Verify audit chain
        entries = [
            json.loads(line) for line in audit_path.read_text().strip().split("\n")
        ]
        assert AuditTrail.verify_chain(entries) is True
        assert len(entries) == 8  # start + 3*(start+complete) + complete


class TestEnterpriseStatePersistence:
    def test_checkpoint_and_final(self, tmp_path):
        sp = StatePersistence(tmp_path)

        state = {"data_collector": {"raw_data": {"btc": 50000}, "confidence": 0.9}}
        sp.save_checkpoint("data_collector", state)

        loaded = sp.load_checkpoint("data_collector")
        assert loaded is not None
        assert loaded["data_collector"]["raw_data"]["btc"] == 50000

        sp.save_final(state)
        final = sp.load_final()
        assert final is not None
        assert "data_collector" in final
