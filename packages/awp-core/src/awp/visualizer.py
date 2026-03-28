"""AWP Workflow Visualizer — Mermaid and ASCII DAG rendering."""

from __future__ import annotations

from .models.orchestration import AWPOrchestrationConfig, ConditionalDependency


def to_mermaid(config: AWPOrchestrationConfig) -> str:
    """Generate a Mermaid flowchart from the orchestration graph.

    Args:
        config: Parsed AWPOrchestrationConfig.

    Returns:
        Mermaid diagram string.
    """
    lines = ["graph TD"]

    for node in config.graph:
        label = node.id
        if not node.enabled:
            label += " [disabled]"

        # Node shape
        if node.loop and node.loop.enabled:
            lines.append(f"    {node.id}(({label}))")  # Circle for loops
        else:
            lines.append(f"    {node.id}[{label}]")

        # Edges
        for dep in node.depends_on:
            if isinstance(dep, ConditionalDependency):
                lines.append(f"    {dep.agent} -->|{dep.condition}| {node.id}")
            else:
                lines.append(f"    {dep} --> {node.id}")

    return "\n".join(lines)


def to_ascii(config: AWPOrchestrationConfig) -> str:
    """Generate an ASCII DAG visualization.

    Shows execution levels (parallel groups).

    Args:
        config: Parsed AWPOrchestrationConfig.

    Returns:
        ASCII art string.
    """
    if not config.graph:
        return "(empty graph)"

    # Topological sort into levels
    levels = _topological_levels(config)

    lines: list[str] = []
    for i, level in enumerate(levels):
        agents_str = ", ".join(level)
        if len(level) > 1:
            lines.append(f"  Level {i}: [{agents_str}]  <- parallel")
        else:
            lines.append(f"  Level {i}: [{agents_str}]")

    return "\n".join(lines)


def _topological_levels(config: AWPOrchestrationConfig) -> list[list[str]]:
    """Sort graph nodes into execution levels."""
    # Build dependency map
    deps: dict[str, set[str]] = {}
    all_ids: list[str] = []

    for node in config.graph:
        all_ids.append(node.id)
        dep_set: set[str] = set()
        for dep in node.depends_on:
            if isinstance(dep, ConditionalDependency):
                dep_set.add(dep.agent)
            else:
                dep_set.add(dep)
        deps[node.id] = dep_set

    levels: list[list[str]] = []
    remaining = set(all_ids)

    while remaining:
        # Find nodes with all dependencies satisfied
        level = [nid for nid in remaining if not deps.get(nid, set()) & remaining]

        if not level:
            # Cycle -- just dump remaining
            levels.append(sorted(remaining))
            break

        levels.append(sorted(level))
        remaining -= set(level)

    return levels
