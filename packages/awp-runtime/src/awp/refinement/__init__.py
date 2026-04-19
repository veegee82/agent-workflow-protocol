"""AWP Refinement Mode — task-local iterative refinement of a deliverable."""

from awp.refinement.gradient import (
    Defect,
    RefinementGradient,
    RejectedGate,
    extract_gradient,
    render_refinement_prefix,
)
from awp.refinement.budget import budget_for_iteration
from awp.refinement.seed import prepare_iteration_workspace

__all__ = [
    "Defect",
    "RefinementGradient",
    "RejectedGate",
    "budget_for_iteration",
    "extract_gradient",
    "prepare_iteration_workspace",
    "render_refinement_prefix",
]
