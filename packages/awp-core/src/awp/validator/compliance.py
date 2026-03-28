"""AWP Autonomy Level checking (A0-A4).

Autonomy levels describe how self-directed a workflow is, from fully
prescribed (A0) to self-organizing (A4).  Security and observability
are cross-cutting concerns required at every level.

Level mapping:
    A0 PRESCRIBED      — Static DAG, predefined agents
    A1 ADAPTIVE         — Conditional execution, loops, fan-out
    A2 DELEGATING       — Manager spawns workers dynamically (delegation loop)
    A3 SELF_TOOLING     — Agents create tools/skills at runtime
    A4 SELF_ORGANIZING  — Recursive delegation, budget distribution

Safety requirements scale with autonomy:
    A0-A1: Security + observability recommended
    A2:    Budget system REQUIRED
    A3:    Safety envelope + budget REQUIRED
    A4:    Safety envelope + budget + observability REQUIRED

Legacy aliases (L0-L5) are provided for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from ..models.manifest import AWPManifest
from ..models.agent import AWPAgent


class AutonomyLevel(IntEnum):
    """AWP autonomy levels — how self-directed is the workflow?"""

    A0_PRESCRIBED = 0  # Static DAG, predefined agents
    A1_ADAPTIVE = 1  # Conditional execution, loops, fan-out
    A2_DELEGATING = 2  # Manager spawns workers dynamically
    A3_SELF_TOOLING = 3  # Agents create tools/skills at runtime
    A4_SELF_ORGANIZING = 4  # Recursive delegation, budget distribution


# Backward-compatible alias
ComplianceLevel = AutonomyLevel

# Legacy name mapping for CLI and old configs
LEVEL_ALIASES: dict[str, AutonomyLevel] = {
    # New names
    "A0": AutonomyLevel.A0_PRESCRIBED,
    "A1": AutonomyLevel.A1_ADAPTIVE,
    "A2": AutonomyLevel.A2_DELEGATING,
    "A3": AutonomyLevel.A3_SELF_TOOLING,
    "A4": AutonomyLevel.A4_SELF_ORGANIZING,
    # Legacy L-names (backward compat)
    "L0": AutonomyLevel.A0_PRESCRIBED,
    "L1": AutonomyLevel.A1_ADAPTIVE,
    "L2": AutonomyLevel.A2_DELEGATING,
    "L3": AutonomyLevel.A3_SELF_TOOLING,
    "L4": AutonomyLevel.A4_SELF_ORGANIZING,
    "L5": AutonomyLevel.A4_SELF_ORGANIZING,  # L5 maps to A4 (highest)
}

LEVEL_NAMES: dict[AutonomyLevel, str] = {
    AutonomyLevel.A0_PRESCRIBED: "Prescribed",
    AutonomyLevel.A1_ADAPTIVE: "Adaptive",
    AutonomyLevel.A2_DELEGATING: "Delegating",
    AutonomyLevel.A3_SELF_TOOLING: "Self-Tooling",
    AutonomyLevel.A4_SELF_ORGANIZING: "Self-Organizing",
}


@dataclass
class ComplianceResult:
    """Result of autonomy level checking."""

    level: AutonomyLevel
    max_achievable: AutonomyLevel
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cross_cutting: dict[str, bool] = field(default_factory=dict)

    @property
    def compliant(self) -> bool:
        return self.level >= self.max_achievable or len(self.errors) == 0

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "Unknown")


def check_compliance(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    workflow_path: Path | None = None,
    target_level: AutonomyLevel = AutonomyLevel.A0_PRESCRIBED,
) -> ComplianceResult:
    """Check AWP autonomy level.

    Args:
        manifest: Parsed AWPManifest.
        agents: Dict of agent_id -> AWPAgent.
        workflow_path: Path to the workflow directory (for file checks).
        target_level: Target autonomy level to check.

    Returns:
        ComplianceResult with achieved level and any issues.
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []
    achieved = AutonomyLevel.A0_PRESCRIBED

    # Cross-cutting: Security + Observability (recommended for all levels)
    cross_cutting = _check_cross_cutting(manifest, warnings)

    # A0: Prescribed — Manifest + 1 Agent + Output Contract + Static Graph
    a0_ok = _check_a0(manifest, agents, checks, errors)
    if not a0_ok:
        return ComplianceResult(
            level=AutonomyLevel.A0_PRESCRIBED,
            max_achievable=target_level,
            checks=checks,
            errors=errors,
            cross_cutting=cross_cutting,
        )

    if target_level < AutonomyLevel.A1_ADAPTIVE:
        return ComplianceResult(
            level=AutonomyLevel.A0_PRESCRIBED,
            max_achievable=target_level,
            checks=checks,
            cross_cutting=cross_cutting,
        )

    # A1: Adaptive — Conditional execution, loops, or fan-out in the graph
    a1_ok = _check_a1(manifest, agents, checks, errors)
    if a1_ok:
        achieved = AutonomyLevel.A1_ADAPTIVE

    if target_level < AutonomyLevel.A2_DELEGATING:
        return ComplianceResult(
            level=achieved,
            max_achievable=target_level,
            checks=checks,
            errors=errors,
            cross_cutting=cross_cutting,
        )

    # A2: Delegating — Delegation loop engine or dynamic worker spawning
    a2_ok = _check_a2(manifest, checks, errors)
    if a2_ok:
        achieved = max(achieved, AutonomyLevel.A2_DELEGATING)

    if target_level < AutonomyLevel.A3_SELF_TOOLING:
        return ComplianceResult(
            level=achieved,
            max_achievable=target_level,
            checks=checks,
            errors=errors,
            cross_cutting=cross_cutting,
        )

    # A3: Self-Tooling — Dynamic tool creation or runtime skill generation
    a3_ok = _check_a3(manifest, agents, checks, errors)
    if a3_ok:
        achieved = max(achieved, AutonomyLevel.A3_SELF_TOOLING)

    if target_level < AutonomyLevel.A4_SELF_ORGANIZING:
        return ComplianceResult(
            level=achieved,
            max_achievable=target_level,
            checks=checks,
            errors=errors,
            cross_cutting=cross_cutting,
        )

    # A4: Self-Organizing — Recursive delegation + budget system
    a4_ok = _check_a4(manifest, checks, errors)
    if a4_ok:
        achieved = max(achieved, AutonomyLevel.A4_SELF_ORGANIZING)

    return ComplianceResult(
        level=achieved,
        max_achievable=target_level,
        checks=checks,
        errors=errors,
        warnings=warnings,
        cross_cutting=cross_cutting,
    )


# -- Cross-cutting: Security + Observability (all levels) ------------------


def _check_cross_cutting(manifest: AWPManifest, warnings: list[str]) -> dict[str, bool]:
    """Check cross-cutting concerns (security + observability)."""
    result: dict[str, bool] = {}

    # Security
    has_security = manifest.security is not None
    result["security_configured"] = has_security
    if not has_security:
        warnings.append("Security config recommended for all workflows")

    # Observability
    has_obs = manifest.observability is not None
    result["observability_configured"] = has_obs
    if not has_obs:
        warnings.append("Observability config recommended for all workflows")

    return result


# -- A0: Prescribed --------------------------------------------------------


def _check_a0(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """A0 Prescribed: Manifest + 1 Agent + Output Contract."""
    ok = True

    checks["manifest_present"] = True
    checks["awp_version_set"] = bool(manifest.awp)
    checks["workflow_name_valid"] = bool(manifest.workflow.name)

    has_agents = len(agents) >= 1
    checks["at_least_one_agent"] = has_agents
    if not has_agents:
        errors.append("A0: At least one agent is required")
        ok = False

    for agent_id, agent in agents.items():
        has_contract = bool(agent.output.contract) or agent.output.format != "json"
        checks[f"agent_{agent_id}_has_contract"] = has_contract
        if not has_contract:
            errors.append(f"A0: Agent '{agent_id}' must have an output contract")
            ok = False

    return ok


# -- A1: Adaptive ----------------------------------------------------------


def _check_a1(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """A1 Adaptive: Orchestration with conditional execution, loops, or fan-out."""
    ok = True

    has_orchestration = manifest.orchestration is not None
    checks["has_orchestration"] = has_orchestration
    if not has_orchestration:
        errors.append("A1: Orchestration config required")
        return False

    orch = manifest.orchestration
    has_graph = bool(getattr(orch, "graph", None))
    has_delegation = getattr(orch, "engine", "dag") == "delegation_loop"
    checks["has_graph_or_delegation"] = has_graph or has_delegation

    if not has_graph and not has_delegation:
        errors.append("A1: Orchestration must define a graph or delegation loop")
        ok = False

    # Check for adaptive features (conditional, loops, fan-out)
    has_adaptive = False
    if has_graph:
        for node in orch.graph:
            if getattr(node, "when", None):
                has_adaptive = True
            if getattr(node, "loop", None) and node.loop.enabled:
                has_adaptive = True
            if getattr(node, "fan_out", None) and node.fan_out.enabled:
                has_adaptive = True
            deps = getattr(node, "depends_on", [])
            for dep in deps:
                if hasattr(dep, "when") and dep.when:
                    has_adaptive = True
    if has_delegation:
        has_adaptive = True  # Delegation loop is inherently adaptive

    checks["has_adaptive_features"] = has_adaptive
    if not has_adaptive:
        # Still A1 if multi-agent DAG (state sharing = composable)
        multi_agent = has_graph and len(orch.graph) >= 2
        checks["multi_agent_dag"] = multi_agent
        if not multi_agent:
            errors.append(
                "A1: Requires adaptive features (when, loop, fan_out) or multi-agent DAG"
            )
            ok = False

    return ok


# -- A2: Delegating --------------------------------------------------------


def _check_a2(
    manifest: AWPManifest,
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """A2 Delegating: Delegation loop engine with dynamic worker spawning."""
    orch = manifest.orchestration
    if not orch:
        errors.append("A2: Orchestration config required")
        return False

    is_delegation = getattr(orch, "engine", "dag") == "delegation_loop"
    has_dl_config = getattr(orch, "delegation_loop", None) is not None
    checks["delegation_loop_engine"] = is_delegation
    checks["delegation_loop_config"] = has_dl_config

    if not is_delegation or not has_dl_config:
        errors.append("A2: Requires engine=delegation_loop with delegation_loop config")
        return False

    # Budget system REQUIRED at A2+
    dl = orch.delegation_loop
    has_budget = getattr(dl, "budget", None) is not None
    checks["has_budget"] = has_budget
    if not has_budget:
        errors.append("A2: Budget system required for delegation loop")
        return False

    return True


# -- A3: Self-Tooling ------------------------------------------------------


def _check_a3(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """A3 Self-Tooling: Dynamic tool creation or runtime skill generation."""
    # Check for dynamic tools config at workflow level
    dt = getattr(manifest, "dynamic_tools", None)
    has_dynamic_tools = dt is not None and getattr(dt, "enabled", False)
    checks["dynamic_tools_enabled"] = has_dynamic_tools

    # Check for agents with tool_creation capability
    has_tool_creator = False
    for agent_id, agent in agents.items():
        caps = getattr(agent, "capabilities", None)
        if caps:
            cm = getattr(caps, "codemode", None)
            if cm and getattr(cm, "tool_creation", False):
                has_tool_creator = True
                break

    checks["has_tool_creator_agent"] = has_tool_creator

    # Check for delegation loop with codemode.tool_creation in manager_controlled
    orch = manifest.orchestration
    dl_allows_tool_creation = False
    if orch and getattr(orch, "delegation_loop", None):
        dl = orch.delegation_loop
        wp = getattr(dl, "worker_policy", None)
        if wp:
            mc = getattr(wp, "manager_controlled", [])
            if "codemode.tool_creation" in mc:
                dl_allows_tool_creation = True
    checks["delegation_allows_tool_creation"] = dl_allows_tool_creation

    is_self_tooling = has_dynamic_tools or has_tool_creator or dl_allows_tool_creation
    if not is_self_tooling:
        errors.append(
            "A3: Requires dynamic_tools.enabled, agent with tool_creation, or delegation loop with tool_creation"
        )
        return False

    # Safety envelope REQUIRED at A3+
    if orch and getattr(orch, "delegation_loop", None):
        dl = orch.delegation_loop
        wp = getattr(dl, "worker_policy", None)
        has_envelope = wp is not None and getattr(wp, "enforced", None) is not None
        checks["has_safety_envelope"] = has_envelope
        if not has_envelope:
            errors.append("A3: Safety envelope (worker_policy.enforced) required")
            return False

    return True


# -- A4: Self-Organizing ---------------------------------------------------


def _check_a4(
    manifest: AWPManifest,
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """A4 Self-Organizing: Recursive delegation with budget distribution."""
    orch = manifest.orchestration
    if not orch:
        errors.append("A4: Orchestration required")
        return False

    dl = getattr(orch, "delegation_loop", None)
    if not dl:
        errors.append("A4: Delegation loop required for self-organizing")
        return False

    # Must allow recursive delegation (max_depth > 1)
    budget = getattr(dl, "budget", None)
    allows_recursion = budget is not None and getattr(budget, "max_depth", 1) > 1
    checks["allows_recursive_delegation"] = allows_recursion
    if not allows_recursion:
        errors.append("A4: budget.max_depth > 1 required for recursive delegation")
        return False

    # Observability REQUIRED at A4
    has_obs = manifest.observability is not None
    checks["observability_required_a4"] = has_obs
    if not has_obs:
        errors.append("A4: Observability required for self-organizing workflows")
        return False

    return True
