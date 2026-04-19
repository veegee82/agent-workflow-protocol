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

EXAMPLES = Path(__file__).parents[3] / "examples" / "workflows"


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

    def test_a3_skill_and_tool_generation(self):
        """Skill + tool generation should achieve A3 Self-Tooling."""
        m = parse_manifest(EXAMPLES / "10-skill-and-tool-generation" / "workflow.awp.yaml")
        agents = {}
        for ad in (EXAMPLES / "10-skill-and-tool-generation" / "agents").iterdir():
            a = ad / "agent.awp.yaml"
            if a.exists():
                agents[ad.name] = parse_agent(a)
        result = check_compliance(m, agents, target_level=AutonomyLevel.A3_SELF_TOOLING)
        assert result.level >= AutonomyLevel.A3_SELF_TOOLING, (
            f"A3 not reached: errors={result.errors}"
        )

    def test_a4_recursive_delegation(self):
        """Recursive delegation (max_depth>1 + observability) should achieve A4."""
        m = parse_manifest(EXAMPLES / "09-recursive-delegation" / "workflow.awp.yaml")
        agents = {}
        for ad in (EXAMPLES / "09-recursive-delegation" / "agents").iterdir():
            a = ad / "agent.awp.yaml"
            if a.exists():
                agents[ad.name] = parse_agent(a)
        result = check_compliance(m, agents, target_level=AutonomyLevel.A4_SELF_ORGANIZING)
        assert result.level >= AutonomyLevel.A4_SELF_ORGANIZING, (
            f"A4 not reached: errors={result.errors}"
        )

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


# -- R33: Deterministic Phase Type -----------------------------------

import sys  # noqa: E402


class TestR33DeterministicPhase:
    """R33 — static check for deterministic phase type."""

    @classmethod
    def setup_class(cls):
        # Make the fixture package importable as ``r33_fixtures`` so the
        # validator can locate its source file via ``importlib.find_spec``.
        fixtures_dir = Path(__file__).parent / "fixtures"
        if str(fixtures_dir) not in sys.path:
            sys.path.insert(0, str(fixtures_dir))
        # Force a clean import — earlier tests may have cached older modules.
        for mod in ("r33", "r33.pure_callable", "r33.impure_callable"):
            sys.modules.pop(mod, None)

    def _make_manifest(self, phases: list[dict]):
        from awp.models.manifest import AWPManifest, WorkflowMetadata
        from awp.models.orchestration import AWPOrchestrationConfig, GraphNode

        orch = AWPOrchestrationConfig(
            graph=[GraphNode(id="drafter", agent="drafter", depends_on=[])],
            phases=phases,
        )
        meta = WorkflowMetadata(
            name="r33-test",
            version="1.0.0",
            description="R33 test workflow",
        )
        return AWPManifest(awp="1.0.0", workflow=meta, orchestration=orch)

    def test_pure_callable_passes(self, tmp_path):
        """A deterministic phase whose callable has no LLM imports passes."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [
                {
                    "id": "assemble",
                    "type": "deterministic",
                    "depends_on": ["drafter"],
                    "callable": "r33.pure_callable:build",
                    "timeout_s": 120,
                    "invariants": [
                        {"kind": "exit_code", "expected": 0},
                    ],
                }
            ]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if e.startswith("R33")]
        assert not r33_errors, f"unexpected R33 errors: {r33_errors}"

    def test_impure_callable_rejected(self, tmp_path):
        """A deterministic phase whose callable imports openai is rejected."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [
                {
                    "id": "assemble",
                    "type": "deterministic",
                    "depends_on": ["drafter"],
                    "callable": "r33.impure_callable:build",
                    "timeout_s": 60,
                    "invariants": [],
                }
            ]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if e.startswith("R33")]
        assert r33_errors, "expected an R33 error for openai import"
        assert any("openai" in e for e in r33_errors)

    def test_malformed_callable_rejected(self, tmp_path):
        """A callable without 'module:func' format is rejected."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [
                {
                    "id": "assemble",
                    "type": "deterministic",
                    "callable": "this_is_not_valid",
                    "timeout_s": 60,
                }
            ]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if e.startswith("R33")]
        assert r33_errors

    def test_timeout_out_of_range_rejected(self, tmp_path):
        """Timeouts < 1 or > 3600 are rejected."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [
                {
                    "id": "assemble",
                    "type": "deterministic",
                    "callable": "r33.pure_callable:build",
                    "timeout_s": 5000,
                }
            ]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if "R33" in e and "timeout_s" in e]
        assert r33_errors

    def test_unknown_dependency_rejected(self, tmp_path):
        """depends_on must resolve to another graph node or phase."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [
                {
                    "id": "assemble",
                    "type": "deterministic",
                    "depends_on": ["does_not_exist"],
                    "callable": "r33.pure_callable:build",
                }
            ]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [
            e for e in result.errors if "R33" in e and "does_not_exist" in e
        ]
        assert r33_errors

    def test_invalid_invariant_shape_rejected(self, tmp_path):
        """An invariant missing its required per-kind fields is rejected."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [
                {
                    "id": "assemble",
                    "type": "deterministic",
                    "callable": "r33.pure_callable:build",
                    "invariants": [
                        # file_size_range requires min/max — omitting fails.
                        {"kind": "file_size_range", "path": "/x"}
                    ],
                }
            ]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if "R33" in e]
        assert r33_errors

    def test_unknown_phase_type_rejected(self, tmp_path):
        """Unknown type discriminator is rejected."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [{"id": "assemble", "type": "banana"}]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if "R33" in e]
        assert r33_errors

    def test_hybrid_type_accepted_at_load(self, tmp_path):
        """Hybrid phases are reserved — loader MUST accept the value."""
        (tmp_path / "agents" / "drafter").mkdir(parents=True)
        m = self._make_manifest(
            [{"id": "assemble", "type": "hybrid"}]
        )
        result = validate_rules(m, {}, tmp_path)
        r33_errors = [e for e in result.errors if "R33" in e]
        # No errors from R33 because the deterministic-only checks are
        # guarded by ``if ptype != "deterministic": continue``.
        assert not r33_errors
