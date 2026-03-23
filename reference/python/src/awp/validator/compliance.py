"""AWP Compliance Level checking (L0-L5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from ..models.manifest import AWPManifest
from ..models.agent import AWPAgent
from ..models.orchestration import AWPOrchestrationConfig
from ..models.communication import CommunicationConfig
from ..models.memory import MemoryConfig
from ..models.observability import ObservabilityConfig
from ..models.security import SecurityConfig


class ComplianceLevel(IntEnum):
    """AWP compliance levels."""
    L0_CORE = 0
    L1_COMPOSABLE = 1
    L2_COMMUNICATIVE = 2
    L3_MEMORABLE = 3
    L4_OBSERVABLE = 4
    L5_ENTERPRISE = 5


@dataclass
class ComplianceResult:
    """Result of compliance checking."""
    level: ComplianceLevel
    max_achievable: ComplianceLevel
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def compliant(self) -> bool:
        return self.level >= self.max_achievable or len(self.errors) == 0


def check_compliance(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    workflow_path: Path | None = None,
    target_level: ComplianceLevel = ComplianceLevel.L0_CORE,
) -> ComplianceResult:
    """Check AWP compliance at a given level.

    Args:
        manifest: Parsed AWPManifest.
        agents: Dict of agent_id -> AWPAgent.
        workflow_path: Path to the workflow directory (for file checks).
        target_level: Target compliance level to check.

    Returns:
        ComplianceResult with achieved level and any issues.
    """
    checks: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []
    achieved = ComplianceLevel.L0_CORE

    # L0: Core -- Manifest + 1 Agent + Output Contract
    l0_ok = _check_l0(manifest, agents, checks, errors)
    if not l0_ok:
        return ComplianceResult(
            level=ComplianceLevel.L0_CORE,
            max_achievable=target_level,
            checks=checks,
            errors=errors,
        )

    if target_level < ComplianceLevel.L1_COMPOSABLE:
        return ComplianceResult(
            level=ComplianceLevel.L0_CORE,
            max_achievable=target_level,
            checks=checks,
        )

    # L1: Composable -- DAG + State Sharing
    l1_ok = _check_l1(manifest, agents, checks, errors)
    if l1_ok:
        achieved = ComplianceLevel.L1_COMPOSABLE

    if target_level < ComplianceLevel.L2_COMMUNICATIVE:
        return ComplianceResult(level=achieved, max_achievable=target_level, checks=checks, errors=errors)

    # L2: Communicative -- Message Bus + Channels
    l2_ok = _check_l2(manifest, checks, errors)
    if l2_ok and l1_ok:
        achieved = ComplianceLevel.L2_COMMUNICATIVE

    if target_level < ComplianceLevel.L3_MEMORABLE:
        return ComplianceResult(level=achieved, max_achievable=target_level, checks=checks, errors=errors)

    # L3: Memorable -- Memory (2+ tiers)
    l3_ok = _check_l3(manifest, checks, errors)
    if l3_ok and l1_ok:
        achieved = max(achieved, ComplianceLevel.L3_MEMORABLE)

    if target_level < ComplianceLevel.L4_OBSERVABLE:
        return ComplianceResult(level=achieved, max_achievable=target_level, checks=checks, errors=errors)

    # L4: Observable -- Tracing + Metrics + Audit
    l4_ok = _check_l4(manifest, checks, errors)
    if l4_ok and l1_ok:
        achieved = max(achieved, ComplianceLevel.L4_OBSERVABLE)

    if target_level < ComplianceLevel.L5_ENTERPRISE:
        return ComplianceResult(level=achieved, max_achievable=target_level, checks=checks, errors=errors)

    # L5: Enterprise -- L0-L4 + Security + Circuit Breaker
    l5_ok = _check_l5(manifest, checks, errors)
    if l5_ok and l1_ok and l2_ok and l3_ok and l4_ok:
        achieved = ComplianceLevel.L5_ENTERPRISE

    return ComplianceResult(
        level=achieved,
        max_achievable=target_level,
        checks=checks,
        errors=errors,
        warnings=warnings,
    )


def _check_l0(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """L0: Core -- Manifest + 1 Agent + Output Contract."""
    ok = True

    # Manifest present and valid
    checks["manifest_present"] = True
    checks["awp_version_set"] = bool(manifest.awp)
    checks["workflow_name_valid"] = bool(manifest.workflow.name)

    # At least one agent
    has_agents = len(agents) >= 1
    checks["at_least_one_agent"] = has_agents
    if not has_agents:
        errors.append("L0: At least one agent is required")
        ok = False

    # Every agent has output contract
    for agent_id, agent in agents.items():
        has_contract = bool(agent.output.contract) or agent.output.format != "json"
        checks[f"agent_{agent_id}_has_contract"] = has_contract
        if not has_contract:
            errors.append(f"L0: Agent '{agent_id}' must have an output contract")
            ok = False

    return ok


def _check_l1(
    manifest: AWPManifest,
    agents: dict[str, AWPAgent],
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """L1: Composable -- DAG + State Sharing."""
    ok = True

    has_orchestration = manifest.orchestration is not None
    checks["has_orchestration"] = has_orchestration
    if not has_orchestration:
        errors.append("L1: Orchestration config required")
        ok = False
        return ok

    orch = manifest.orchestration
    has_graph = bool(orch.graph) if hasattr(orch, "graph") else False
    checks["has_graph"] = has_graph
    if not has_graph:
        errors.append("L1: Orchestration must define a graph with at least one node")
        ok = False

    return ok


def _check_l2(
    manifest: AWPManifest,
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """L2: Communicative -- Message Bus + Channels."""
    has_comm = manifest.communication is not None
    checks["has_communication"] = has_comm
    if not has_comm:
        errors.append("L2: Communication config required")
        return False

    comm = manifest.communication
    has_bus = hasattr(comm, "bus") and comm.bus is not None
    checks["has_bus"] = has_bus
    if not has_bus:
        errors.append("L2: Message bus configuration required")
        return False

    return True


def _check_l3(
    manifest: AWPManifest,
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """L3: Memorable -- Memory with 2+ tiers."""
    has_memory = manifest.memory is not None
    checks["has_memory"] = has_memory
    if not has_memory:
        errors.append("L3: Memory config required")
        return False

    mem = manifest.memory
    tiers = 0
    if hasattr(mem, "long_term") and mem.long_term and mem.long_term.enabled:
        tiers += 1
    if hasattr(mem, "daily_log") and mem.daily_log and mem.daily_log.enabled:
        tiers += 1
    if hasattr(mem, "episodic") and mem.episodic and mem.episodic.enabled:
        tiers += 1
    if hasattr(mem, "semantic") and mem.semantic and mem.semantic.enabled:
        tiers += 1

    checks["memory_2_plus_tiers"] = tiers >= 2
    if tiers < 2:
        errors.append(f"L3: At least 2 memory tiers required, found {tiers}")
        return False

    return True


def _check_l4(
    manifest: AWPManifest,
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """L4: Observable -- Tracing + Metrics + Audit."""
    has_obs = manifest.observability is not None
    checks["has_observability"] = has_obs
    if not has_obs:
        errors.append("L4: Observability config required")
        return False

    obs = manifest.observability
    ok = True

    has_tracing = hasattr(obs, "tracing") and obs.tracing and obs.tracing.enabled
    checks["tracing_enabled"] = has_tracing
    if not has_tracing:
        errors.append("L4: Tracing must be enabled")
        ok = False

    has_metrics = hasattr(obs, "metrics") and obs.metrics and obs.metrics.enabled
    checks["metrics_enabled"] = has_metrics
    if not has_metrics:
        errors.append("L4: Metrics must be enabled")
        ok = False

    has_audit = hasattr(obs, "audit") and obs.audit and obs.audit.enabled
    checks["audit_enabled"] = has_audit
    if not has_audit:
        errors.append("L4: Audit must be enabled")
        ok = False

    return ok


def _check_l5(
    manifest: AWPManifest,
    checks: dict[str, bool],
    errors: list[str],
) -> bool:
    """L5: Enterprise -- Security + Circuit Breaker."""
    has_security = manifest.security is not None
    checks["has_security"] = has_security
    if not has_security:
        errors.append("L5: Security config required")
        return False

    sec = manifest.security
    has_cb = hasattr(sec, "circuit_breaker") and sec.circuit_breaker and sec.circuit_breaker.enabled
    checks["circuit_breaker_enabled"] = has_cb
    if not has_cb:
        errors.append("L5: Circuit breaker must be enabled")
        return False

    return True
