"""End-to-end tests for AWP protocol tooling."""

import json
import tempfile
from pathlib import Path

import pytest

from awp import AWPAgent, __version__
from awp.parser import parse_manifest, parse_agent
from awp.validator import validate_graph, validate_contracts, check_compliance, ComplianceLevel
from awp.validator.rules import validate_rules
from awp.validator.schema_validator import validate_schema, validate_schema_desc
from awp.schema_generator import generate_output_schema, generate_output_schema_desc
from awp.visualizer import to_mermaid, to_ascii
from awp.packager import pack_workflow, unpack_workflow
from awp.runtime.agent import StandaloneAgent
from awp.runtime.runner import WorkflowRunner
from awp.agent import AWPAgent as AWPAgentABC

EXAMPLES = Path(__file__).parents[3] / "examples"


class TestEndToEnd:
    """Full pipeline: parse -> validate -> visualize -> pack -> unpack."""

    def test_full_pipeline_hello_world(self):
        wf_dir = EXAMPLES / "01-hello-world"

        # 1. Parse manifest
        manifest = parse_manifest(wf_dir / "workflow.awp.yaml")
        assert manifest.workflow.name == "hello-world"

        # 2. Parse all agents
        agents = {}
        for ad in sorted((wf_dir / "agents").iterdir()):
            awp = ad / "agent.awp.yaml"
            if awp.exists():
                agents[ad.name] = parse_agent(awp)
        assert len(agents) == 1

        # 3. Validate graph
        graph_result = validate_graph(manifest.orchestration)
        assert graph_result.valid

        # 4. Validate contracts
        contract_result = validate_contracts(agents, manifest.orchestration)
        assert contract_result.valid

        # 5. Check compliance
        compliance = check_compliance(manifest, agents, wf_dir, ComplianceLevel.L0_CORE)
        assert compliance.level >= ComplianceLevel.L0_CORE

        # 6. Validate rules
        rules = validate_rules(manifest, agents, wf_dir)
        real_errors = [e for e in rules.errors if "R3" not in e]
        assert len(real_errors) == 0, f"Rule errors: {real_errors}"

        # 7. Validate schemas
        for agent_id in agents:
            schema_path = wf_dir / "agents" / agent_id / "workflow" / "output_schema" / "output_schema.json"
            if schema_path.exists():
                assert validate_schema(schema_path).valid

        # 8. Visualize
        ascii_viz = to_ascii(manifest.orchestration)
        assert "greeter" in ascii_viz

        mermaid_viz = to_mermaid(manifest.orchestration)
        assert "greeter" in mermaid_viz

    def test_full_pipeline_research_pipeline(self):
        wf_dir = EXAMPLES / "02-research-pipeline"

        manifest = parse_manifest(wf_dir / "workflow.awp.yaml")
        agents = {}
        for ad in sorted((wf_dir / "agents").iterdir()):
            awp = ad / "agent.awp.yaml"
            if awp.exists():
                agents[ad.name] = parse_agent(awp)
        assert len(agents) == 3

        # Validate
        assert validate_graph(manifest.orchestration).valid
        assert validate_contracts(agents, manifest.orchestration).valid

        # Compliance L1
        c = check_compliance(manifest, agents, wf_dir, ComplianceLevel.L1_COMPOSABLE)
        assert c.level >= ComplianceLevel.L1_COMPOSABLE

        # Visualize shows 3 agents
        ascii_viz = to_ascii(manifest.orchestration)
        assert "planner" in ascii_viz
        assert "researcher" in ascii_viz
        assert "writer" in ascii_viz

    def test_pack_unpack(self):
        """Pack a workflow, unpack it, verify contents match."""
        wf_dir = EXAMPLES / "01-hello-world"

        with tempfile.TemporaryDirectory() as tmp:
            # Pack
            archive = pack_workflow(wf_dir, Path(tmp) / "test.awp.zip")
            assert archive.exists()
            assert archive.suffix == ".zip"

            # Unpack
            out_dir = Path(tmp) / "unpacked"
            unpack_workflow(archive, out_dir)

            # Verify
            assert (out_dir / "workflow.awp.yaml").exists()
            assert (out_dir / "agents" / "greeter" / "agent.awp.yaml").exists()
            assert (out_dir / "agents" / "greeter" / "agent.py").exists()

            # Re-parse unpacked
            m = parse_manifest(out_dir / "workflow.awp.yaml")
            assert m.workflow.name == "hello-world"


class TestSchemaGenerator:
    """Test output schema generation from contracts."""

    def test_generate_schema(self):
        from awp.models.agent import OutputField
        contract = {
            "result": OutputField(type="string", description="Result", required=True),
            "confidence": OutputField(
                type="number", minimum=0.0, maximum=1.0,
                description="Confidence", required=True,
            ),
        }
        schema = generate_output_schema(contract)
        assert schema["type"] == "object"
        assert "result" in schema["properties"]
        assert "confidence" in schema["properties"]
        assert "confidence" in schema["required"]

    def test_auto_adds_confidence(self):
        from awp.models.agent import OutputField
        contract = {
            "result": OutputField(type="string", description="Result", required=True),
        }
        schema = generate_output_schema(contract)
        assert "confidence" in schema["properties"]
        assert "confidence" in schema["required"]

    def test_generate_desc(self):
        from awp.models.agent import OutputField
        contract = {
            "result": OutputField(type="string", description="The result"),
            "confidence": OutputField(type="number", description="Score"),
        }
        desc = generate_output_schema_desc(contract)
        assert desc["result"] == "The result"
        assert desc["confidence"] == "Score"


class TestAWPAgentInterface:
    """Test the AWPAgent abstract interface."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AWPAgentABC()

    def test_concrete_implementation(self):
        class MyAgent(AWPAgentABC):
            @property
            def name(self):
                return "test"

            def run(self, task, state):
                return {self.name: {"result": task, "confidence": 1.0}}

        agent = MyAgent()
        assert agent.name == "test"
        result = agent.run("hello", {})
        assert result["test"]["confidence"] == 1.0


class TestStandaloneAgent:
    """Test StandaloneAgent initialization (no LLM calls)."""

    def test_init(self):
        agent_dir = EXAMPLES / "01-hello-world" / "agents" / "greeter"
        wf_dir = EXAMPLES / "01-hello-world"
        agent = StandaloneAgent(agent_dir, wf_dir)
        assert agent.name == "greeter"

    def test_load_prompt(self):
        agent_dir = EXAMPLES / "01-hello-world" / "agents" / "greeter"
        wf_dir = EXAMPLES / "01-hello-world"
        agent = StandaloneAgent(agent_dir, wf_dir)
        prompt = agent._build_system_prompt()
        assert len(prompt) > 0


class TestWorkflowRunner:
    """Test WorkflowRunner initialization (no LLM calls)."""

    def test_init(self):
        runner = WorkflowRunner(EXAMPLES / "01-hello-world")
        assert runner.name == "hello-world"

    def test_topological_levels(self):
        runner = WorkflowRunner(EXAMPLES / "02-research-pipeline")
        levels = runner._topological_levels(runner._manifest.orchestration)
        assert len(levels) >= 2
        # planner should be in first level
        assert "planner" in levels[0]


class TestVersion:
    def test_version(self):
        assert __version__ == "1.0.0"
