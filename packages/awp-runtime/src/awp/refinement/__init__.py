"""AWP Refinement Mode — task-local iterative refinement of a deliverable."""

from awp.refinement.gradient import (
    Defect,
    RefinementGradient,
    RejectedGate,
    extract_gradient,
    render_refinement_prefix,
)

__all__ = [
    "Defect",
    "RefinementGradient",
    "RejectedGate",
    "extract_gradient",
    "render_refinement_prefix",
]
