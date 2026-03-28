"""Test AWP validators."""

from pathlib import Path

from awp.parser import parse_manifest, parse_agent
from awp.validator import (
    validate_graph,
    validate_contracts,
    check_compliance,
    AutonomyLevel,
    ComplianceLevel,
)
from awp.validator.rules import validate_rules
from awp.validator.schema_validator import validate_schema, validate_schema_desc
from awp.models.orchestration import (
    AWPOrchestrationConfig,
    GraphNode,
    ConditionalDependency,
)

EXAMPLES = Path(__file__).parents[3] / "examples"


# -- Graph validator -------------------------------------------------


class TestGraphValidator:
    def test_valid_dag(self):
        orch = AWPOrchestrationConfig(
            graph=[
                GraphNode(id="a", agent="a", depends_on=[]),
                GraphNode(id="b", agent="b", depends_on=["a"]),
                GraphNode(id="c", agent="c", depends_on=["b"]),
            ]
        )
        result = validate_graph(orch)
        assert result.valid

    def test_duplicate_ids(self):
        orch = AWPOrchestrationConfig(
            graph=[
                GraphNode(id="a", agent="a"),
                GraphNode(id="a", agent="a"),
            ]
        )
        result = validate_graph(orch)
        assert not result.valid
        assert any("R2" in e for e in result.errors)

    def test_missing_dependency(self):
        orch = AWPOrchestrationConfig(
            graph=[
                GraphNode(id="a", agent="a", depends_on=["nonexistent"]),
            ]
        )
        result = validate_graph(orch)
        assert not result.valid
        assert any("R6" in e for e in result.errors)

    def test_cycle_detection(self):
        orch = AWPOrchestrationConfig(
            graph=[
                GraphNode(id="a", agent="a", depends_on=["b"]),
                GraphNode(id="b", agent="b", depends_on=["a"]),
            ]
        )
        result = validate_graph(orch)
        assert not result.valid
        assert any("R7" in e for e in result.errors)

    def test_empty_graph(self):
        orch = AWPOrchestrationConfig(graph=[])
        result = validate_graph(orch)
        assert not result.valid

    def test_conditional_dependency(self):
        orch = AWPOrchestrationConfig(
            graph=[
                GraphNode(id="a", agent="a"),
                GraphNode(
                    id="b",
                    agent="b",
                    depends_on=[
                        ConditionalDependency(agent="a", condition="success"),
                    ],
                ),
            ]
        )
        result = validate_graph(orch)
        assert result.valid


# -- Contract validator ----------------------------------------------


class TestContractValidator:
    def test_confidence_required(self):
        """R17: Every agent must have confidence in output.contract."""
        a = parse_agent(
            EXAMPLES / "01-hello-world" / "agents" / "greeter" / "agent.awp.yaml"
        )
        result = validate_contracts({"greeter": a})
        assert result.valid

    def test_missing_confidence(self):
        from awp.models.agent import AWPAgent, OutputConfig

        a = AWPAgent(
            awp_agent="1.0.0",
            identity={"id": "test", "role": "test", "description": "test"},
            model={"name": "m"},
            prompt={"system": "s"},
            output=OutputConfig(
                format="json",
                contract={
                    "result": {"type": "string"},
                },
            ),
        )
        result = validate_contracts({"test": a})
        assert not result.valid
        assert any("R17" in e for e in result.errors)


# -- Schema validator ------------------------------------------------


class TestSchemaValidator:
    def test_valid_schemas(self):
        for example_dir in sorted(EXAMPLES.iterdir()):
            if not example_dir.is_dir():
                continue
            if not (example_dir / "agents").is_dir():
                continue
            for agent_dir in sorted((example_dir / "agents").iterdir()):
                schema = agent_dir / "workflow" / "output_schema" / "output_schema.json"
                if schema.exists():
                    result = validate_schema(schema)
                    assert result.valid, f"Schema invalid: {schema} -- {result.errors}"

    def test_schema_desc_match(self):
        for example_dir in sorted(EXAMPLES.iterdir()):
            if not example_dir.is_dir():
                continue
            if not (example_dir / "agents").is_dir():
                continue
            for agent_dir in sorted((example_dir / "agents").iterdir()):
                schema = agent_dir / "workflow" / "output_schema" / "output_schema.json"
                desc = (
                    agent_dir
                    / "workflow"
                    / "output_schema_desc"
                    / "output_schema_desc.json"
                )
                if schema.exists() and desc.exists():
                    result = validate_schema_desc(schema, desc)
                    assert result.valid, (
                        f"Schema desc mismatch: {agent_dir.name} -- {result.errors}"
                    )


# -- Compliance checker ----------------------------------------------


class TestCompliance:
    def test_a0_hello_world(self):
        """Hello world should achieve A0 Prescribed."""
        m = parse_manifest(EXAMPLES / "01-hello-world" / "workflow.awp.yaml")
        agents = {}
        for ad in (EXAMPLES / "01-hello-world" / "agents").iterdir():
            a = ad / "agent.awp.yaml"
            if a.exists():
                agents[ad.name] = parse_agent(a)
        result = check_compliance(m, agents, target_level=AutonomyLevel.A0_PRESCRIBED)
        assert result.level >= AutonomyLevel.A0_PRESCRIBED

    def test_a1_research_pipeline(self):
        """Research pipeline (multi-agent DAG) should achieve A1 Adaptive."""
        m = parse_manifest(EXAMPLES / "02-research-pipeline" / "workflow.awp.yaml")
        agents = {}
        for ad in (EXAMPLES / "02-research-pipeline" / "agents").iterdir():
            a = ad / "agent.awp.yaml"
            if a.exists():
                agents[ad.name] = parse_agent(a)
        result = check_compliance(m, agents, target_level=AutonomyLevel.A1_ADAPTIVE)
        assert result.level >= AutonomyLevel.A1_ADAPTIVE

    def test_a2_delegation_loop(self):
        """Delegation loop example should achieve A2 Delegating."""
        m = parse_manifest(EXAMPLES / "08-delegation-loop" / "workflow.awp.yaml")
        agents = {}
        for ad in (EXAMPLES / "08-delegation-loop" / "agents").iterdir():
            a = ad / "agent.awp.yaml"
            if a.exists():
                agents[ad.name] = parse_agent(a)
        result = check_compliance(m, agents, target_level=AutonomyLevel.A2_DELEGATING)
        assert result.level >= AutonomyLevel.A2_DELEGATING

    def test_backward_compat_alias(self):
        """ComplianceLevel alias should work."""
        assert ComplianceLevel.A0_PRESCRIBED == AutonomyLevel.A0_PRESCRIBED


# -- Rules validator -------------------------------------------------


class TestRules:
    def test_hello_world_passes(self):
        m = parse_manifest(EXAMPLES / "01-hello-world" / "workflow.awp.yaml")
        agents = {}
        for ad in (EXAMPLES / "01-hello-world" / "agents").iterdir():
            a = ad / "agent.awp.yaml"
            if a.exists():
                agents[ad.name] = parse_agent(a)
        result = validate_rules(m, agents, EXAMPLES / "01-hello-world")
        assert result.valid, f"Rules failed: {result.errors}"

    def test_all_examples_pass_rules(self):
        for example_dir in sorted(EXAMPLES.iterdir()):
            if not example_dir.is_dir():
                continue
            mf = example_dir / "workflow.awp.yaml"
            if not mf.exists():
                continue
            m = parse_manifest(mf)
            agents = {}
            for ad in (example_dir / "agents").iterdir():
                a = ad / "agent.awp.yaml"
                if a.exists():
                    agents[ad.name] = parse_agent(a)
            result = validate_rules(m, agents, example_dir)
            # Filter out R3 warnings (class_name check requires reading .py)
            real_errors = [e for e in result.errors if "R3" not in e]
            assert len(real_errors) == 0, f"{example_dir.name}: {real_errors}"
