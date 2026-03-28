"""DAG graph validation for AWP orchestration."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from ..models.orchestration import AWPOrchestrationConfig, ConditionalDependency


@dataclass
class ValidationResult:
    """Result of a validation check."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_graph(config: AWPOrchestrationConfig) -> ValidationResult:
    """Validate the orchestration graph.

    Checks:
    - R2: Unique agent IDs (snake_case)
    - R6: All depends_on references exist
    - R7: No cycles (unless within declared loops)
    - No orphan agents (all reachable from roots)

    Args:
        config: Parsed AWPOrchestrationConfig

    Returns:
        ValidationResult with any errors found.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not config.graph:
        return ValidationResult(
            valid=False, errors=["Graph must have at least one node"]
        )

    # Collect all node IDs
    node_ids = [node.id for node in config.graph]

    # R2: Unique IDs
    seen: set[str] = set()
    for nid in node_ids:
        if nid in seen:
            errors.append(f"R2: Duplicate agent ID: '{nid}'")
        seen.add(nid)

    node_set = set(node_ids)

    # R6: All depends_on reference existing agents
    for node in config.graph:
        for dep in node.depends_on:
            dep_id = dep.agent if isinstance(dep, ConditionalDependency) else dep
            if dep_id not in node_set:
                errors.append(
                    f"R6: Agent '{node.id}' depends on '{dep_id}' which doesn't exist"
                )

    # R7: Cycle detection (Kahn's algorithm)
    loop_agents = {node.id for node in config.graph if node.loop and node.loop.enabled}
    cycle_errors = _detect_cycles(config.graph, loop_agents)
    errors.extend(cycle_errors)

    # Orphan check
    orphan_warnings = _check_orphans(config.graph, node_set)
    warnings.extend(orphan_warnings)

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _detect_cycles(
    graph: list,
    loop_agents: set[str],
) -> list[str]:
    """Detect cycles using Kahn's algorithm. Cycles within loop agents are allowed."""
    errors: list[str] = []

    # Build adjacency and in-degree
    in_degree: dict[str, int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)
    all_nodes: set[str] = set()

    for node in graph:
        all_nodes.add(node.id)
        for dep in node.depends_on:
            dep_id = dep.agent if isinstance(dep, ConditionalDependency) else dep
            # Skip edges where both endpoints are loop agents
            if node.id in loop_agents and dep_id in loop_agents:
                continue
            adjacency[dep_id].append(node.id)
            in_degree[node.id] += 1

    # Initialize nodes with no incoming edges
    for nid in all_nodes:
        if nid not in in_degree:
            in_degree[nid] = 0

    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    visited = 0

    while queue:
        current = queue.popleft()
        visited += 1
        for neighbor in adjacency[current]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited < len(all_nodes):
        remaining = [nid for nid in all_nodes if in_degree[nid] > 0]
        errors.append(f"R7: Cycle detected involving agents: {sorted(remaining)}")

    return errors


def _check_orphans(graph: list, node_set: set[str]) -> list[str]:
    """Check for agents not reachable from any root."""
    warnings: list[str] = []

    # Build reverse adjacency (who depends on whom)
    has_dependents: set[str] = set()
    roots: set[str] = set()

    for node in graph:
        if not node.depends_on:
            roots.add(node.id)
        for dep in node.depends_on:
            dep_id = dep.agent if isinstance(dep, ConditionalDependency) else dep
            has_dependents.add(dep_id)

    # Forward reachability from roots
    reachable: set[str] = set()
    adjacency: dict[str, list[str]] = defaultdict(list)
    for node in graph:
        for dep in node.depends_on:
            dep_id = dep.agent if isinstance(dep, ConditionalDependency) else dep
            adjacency[dep_id].append(node.id)

    queue = deque(roots)
    while queue:
        current = queue.popleft()
        if current in reachable:
            continue
        reachable.add(current)
        for neighbor in adjacency[current]:
            queue.append(neighbor)

    orphans = node_set - reachable
    if orphans:
        warnings.append(f"Orphan agents (unreachable from roots): {sorted(orphans)}")

    return warnings
