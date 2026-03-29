"""Test AWP YAML parsers."""

import pytest
from pathlib import Path

from awp.parser import parse_manifest, parse_agent, resolve_templates
from awp.parser.template import _resolve_dotted

EXAMPLES = Path(__file__).parents[3] / "examples" / "workflows"
CONFORMANCE = Path(__file__).parents[3] / "conformance" / "fixtures"


# -- Template resolution ---------------------------------------------


class TestTemplateResolution:
    def test_simple(self):
        result = resolve_templates("{{name}}", {"name": "hello"})
        assert result == "hello"

    def test_nested(self):
        ctx = {"workflow": {"settings": {"custom": {"domain": "finance"}}}}
        result = resolve_templates("{{workflow.settings.custom.domain}}", ctx)
        assert result == "finance"

    def test_preserves_type(self):
        result = resolve_templates("{{count}}", {"count": 42})
        assert result == 42

    def test_partial(self):
        result = resolve_templates("hello {{name}}!", {"name": "world"})
        assert result == "hello world!"

    def test_missing_key(self):
        result = resolve_templates("{{missing}}", {})
        assert result == "{{missing}}"

    def test_dict_recursion(self):
        data = {"a": "{{x}}", "b": {"c": "{{y}}"}}
        result = resolve_templates(data, {"x": "1", "y": "2"})
        assert result == {"a": "1", "b": {"c": "2"}}

    def test_list_recursion(self):
        data = ["{{a}}", "{{b}}"]
        result = resolve_templates(data, {"a": "x", "b": "y"})
        assert result == ["x", "y"]

    def test_resolve_dotted(self):
        ctx = {"a": {"b": {"c": "deep"}}}
        assert _resolve_dotted("a.b.c", ctx) == "deep"
        assert _resolve_dotted("a.b.missing", ctx) is None


# -- Manifest parsing ------------------------------------------------


class TestManifestParsing:
    def test_hello_world(self):
        m = parse_manifest(EXAMPLES / "01-hello-world" / "workflow.awp.yaml")
        assert m.workflow.name == "hello-world"
        assert m.awp == "1.0.0"
        assert m.orchestration is not None
        assert len(m.orchestration.graph) >= 1

    def test_research_pipeline(self):
        m = parse_manifest(EXAMPLES / "02-research-pipeline" / "workflow.awp.yaml")
        assert m.workflow.name == "research-pipeline"
        assert len(m.orchestration.graph) == 3

    def test_chat_team(self):
        m = parse_manifest(EXAMPLES / "03-chat-team" / "workflow.awp.yaml")
        assert m.communication is not None

    def test_memory_workflow(self):
        m = parse_manifest(EXAMPLES / "04-memory-workflow" / "workflow.awp.yaml")
        assert m.memory is not None

    def test_enterprise(self):
        m = parse_manifest(EXAMPLES / "06-enterprise" / "workflow.awp.yaml")
        assert m.orchestration is not None
        assert m.security is not None

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_manifest("/nonexistent/workflow.awp.yaml")

    def test_conformance_valid(self):
        for f in sorted(CONFORMANCE.glob("valid/*.yaml")):
            m = parse_manifest(f)
            assert m.awp == "1.0.0", f"Failed: {f.name}"

    def test_conformance_invalid_missing_awp(self):
        with pytest.raises(Exception):
            parse_manifest(CONFORMANCE / "invalid" / "missing-awp-version.yaml")


# -- Agent parsing ---------------------------------------------------


class TestAgentParsing:
    def test_greeter(self):
        a = parse_agent(
            EXAMPLES / "01-hello-world" / "agents" / "greeter" / "agent.awp.yaml"
        )
        assert a.identity.id == "greeter"
        assert a.awp_agent == "1.0.0"

    def test_all_example_agents(self):
        count = 0
        for example_dir in sorted(EXAMPLES.iterdir()):
            if not example_dir.is_dir():
                continue
            agents_dir = example_dir / "agents"
            if not agents_dir.exists():
                continue
            for agent_dir in sorted(agents_dir.iterdir()):
                awp_yaml = agent_dir / "agent.awp.yaml"
                if awp_yaml.exists():
                    a = parse_agent(awp_yaml)
                    assert a.identity.id == agent_dir.name
                    assert a.model.name is not None
                    count += 1
        assert count >= 11, f"Expected at least 11 agents, found {count}"
