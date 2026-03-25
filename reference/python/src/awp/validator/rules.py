"""Rule validation (R1-R26) for AWP workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models.agent import AWPAgent
from ..models.manifest import AWPManifest
from ..models.orchestration import AWPOrchestrationConfig, ConditionalDependency
from ..models.common import RESERVED_TOOL_NAMESPACES


@dataclass
class ValidationResult:
    """Result of a validation check."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_rules(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    workflow_path: Path,
) -> ValidationResult:
    """Validate all rules (R1-R26) against AWP structures.

    Args:
        manifest: Parsed AWPManifest.
        agents: Dict of agent_id -> AWPAgent.
        workflow_path: Path to workflow directory on disk.

    Returns:
        ValidationResult with any rule violations.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # R1: project.name == directory name
    dir_name = workflow_path.name
    # Strip numeric prefix (e.g., "01-hello-world" -> "hello-world")
    stripped_dir = re.sub(r"^\d+-", "", dir_name)
    if manifest.workflow.name != dir_name:
        # Check with underscore/hyphen normalization and stripped prefix
        name_norm = manifest.workflow.name.replace("-", "_")
        dir_norm = dir_name.replace("-", "_")
        stripped_norm = stripped_dir.replace("-", "_")
        if name_norm != dir_norm and name_norm != stripped_norm:
            errors.append(
                f"R1: workflow.name '{manifest.workflow.name}' doesn't match "
                f"directory name '{dir_name}'"
            )

    # R2: Unique agent names, snake_case
    orch = manifest.orchestration
    if orch and hasattr(orch, "graph"):
        seen_ids: set[str] = set()
        for node in orch.graph:
            if node.id in seen_ids:
                errors.append(f"R2: Duplicate agent ID: '{node.id}'")
            seen_ids.add(node.id)

            if not re.match(r"^[a-z][a-z0-9_]*$", node.id):
                errors.append(f"R2: Agent ID '{node.id}' must be snake_case")

    # R3: Agent class must be "Agent"
    for agent_id, agent in agents.items():
        if agent.runtime.class_name != "Agent":
            errors.append(
                f"R3: Agent '{agent_id}' class_name must be 'Agent', "
                f"got '{agent.runtime.class_name}'"
            )

    # R5: agent_path is derived
    for agent_id in agents:
        expected = f"workflows/{manifest.workflow.name}/agents/{agent_id}"
        agent_dir = workflow_path / "agents" / agent_id
        if not agent_dir.exists():
            errors.append(f"R5/R9: Agent directory not found: {agent_dir}")

    # R6: depends_on references exist
    if orch and hasattr(orch, "graph"):
        node_ids = {n.id for n in orch.graph}
        for node in orch.graph:
            for dep in node.depends_on:
                dep_id = dep.agent if isinstance(dep, ConditionalDependency) else dep
                if dep_id not in node_ids:
                    errors.append(
                        f"R6: Agent '{node.id}' depends on '{dep_id}' "
                        f"which doesn't exist in graph"
                    )

    # R9/R11: Agent directory completeness
    for agent_id in agents:
        agent_dir = workflow_path / "agents" / agent_id
        if not agent_dir.exists():
            continue  # Already reported in R5

        required_files = [
            agent_dir / "agent.py",
            agent_dir / "workflow" / "instructions" / "SYSTEM_PROMPT.md",
            agent_dir / "workflow" / "prompt" / "00_INTRO.md",
            agent_dir / "workflow" / "output_schema" / "output_schema.json",
            agent_dir / "workflow" / "output_schema_desc" / "output_schema_desc.json",
        ]

        # R11: Check agent.awp.yaml OR agent.yaml
        has_awp_yaml = (agent_dir / "agent.awp.yaml").exists()
        has_legacy_yaml = (agent_dir / "agent.yaml").exists()
        if not has_awp_yaml and not has_legacy_yaml:
            errors.append(f"R11: Agent '{agent_id}' missing agent.awp.yaml")

        for req_file in required_files:
            if not req_file.exists():
                errors.append(f"R11: Agent '{agent_id}' missing {req_file.name}")

    # R13/R14: Tool configuration consistency
    for agent_id, agent in agents.items():
        caps = agent.capabilities
        if caps and hasattr(caps, "tools"):
            tools = caps.tools
            if not tools.enabled and tools.max_calls != 0:
                errors.append(
                    f"R14: Agent '{agent_id}' has tools.enabled=false "
                    f"but max_calls={tools.max_calls} (must be 0)"
                )

    # R15: Custom tool namespace collision
    # Built-in tool FQNs that may be overridden with local implementations.
    # These are tools defined in the AWP spec (tools-reference.md) that custom
    # implementations may provide when no full AWP runtime is available.
    BUILTIN_TOOL_FQNS = frozenset({
        "web.search", "http.request",
        "file.read", "file.write", "file.list",
        "shell.execute",
        "memory.read", "memory.write", "memory.search", "memory.curate",
        "agent.send_message", "agent.list_messages",
        "arithmetic.add", "arithmetic.subtract", "arithmetic.multiply",
        "arithmetic.divide",
    })
    mcp_dir = workflow_path / "mcp"
    tools_dir = workflow_path / "tools"
    for tools_path in [mcp_dir, tools_dir]:
        if tools_path.exists():
            for py_file in tools_path.glob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                # Check for @app.tool("namespace.action") decorators
                for match in re.finditer(
                    r'@app\.tool\(["\']([^"\']+)["\']\)', content
                ):
                    fqn = match.group(1)
                    # Allow overriding known built-in tools with local
                    # implementations (tool implementation mode).
                    if fqn in BUILTIN_TOOL_FQNS:
                        continue
                    namespace = fqn.split(".")[0] if "." in fqn else fqn
                    if namespace in RESERVED_TOOL_NAMESPACES:
                        errors.append(
                            f"R15: Custom tool '{fqn}' in {py_file.name} "
                            f"uses reserved namespace '{namespace}'"
                        )

    # R17: Confidence field in output contracts
    for agent_id, agent in agents.items():
        if agent.output.format == "json":
            if "confidence" not in agent.output.contract:
                errors.append(
                    f"R17: Agent '{agent_id}' must have 'confidence' "
                    f"in output.contract"
                )

    # R25: Dynamic tool namespace compliance
    # R26: Dynamic tool creation requires Code Mode and workflow-level flag
    dynamic_tools_cfg = getattr(manifest, "dynamic_tools", None)
    dynamic_tools_enabled = (
        dynamic_tools_cfg is not None
        and getattr(dynamic_tools_cfg, "enabled", False)
    )
    allowed_namespaces = (
        getattr(dynamic_tools_cfg, "allowed_namespaces", ["dynamic"])
        if dynamic_tools_cfg
        else ["dynamic"]
    )

    for agent_id, agent in agents.items():
        caps = agent.capabilities
        if not caps or not hasattr(caps, "codemode"):
            continue
        codemode = caps.codemode
        if codemode is None:
            continue

        tool_creation = getattr(codemode, "tool_creation", False)
        if not tool_creation:
            continue

        # R26: tool_creation requires codemode.enabled
        if not codemode.enabled:
            errors.append(
                f"R26: Agent '{agent_id}' has tool_creation=true but "
                f"codemode.enabled=false"
            )

        # R26: tool_creation requires workflow-level dynamic_tools.enabled
        if not dynamic_tools_enabled:
            errors.append(
                f"R26: Agent '{agent_id}' has tool_creation=true but "
                f"dynamic_tools.enabled is false or not set in workflow.awp.yaml"
            )

        # R25: namespace must not be reserved
        ns = getattr(codemode, "tool_creation_namespace", "dynamic")
        if ns in RESERVED_TOOL_NAMESPACES:
            errors.append(
                f"R25: Agent '{agent_id}' tool_creation_namespace '{ns}' "
                f"is a reserved namespace"
            )

        # R25: namespace must be in workflow-level allowed_namespaces
        if dynamic_tools_enabled and ns not in allowed_namespaces:
            errors.append(
                f"R25: Agent '{agent_id}' tool_creation_namespace '{ns}' "
                f"is not in dynamic_tools.allowed_namespaces: {allowed_namespaces}"
            )

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)
