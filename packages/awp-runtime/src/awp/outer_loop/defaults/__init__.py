"""Hardcoded v0 fallback content for outer-loop artifacts.

Every file in this package exposes a single module-level ``CONTENT`` string
that represents the v0 (pre-refactor) version of one prompt artifact. The
:class:`awp.outer_loop.ArtifactRegistry` falls back to these strings when no
database entry exists, guaranteeing behavior-preserving defaults.
"""

from __future__ import annotations

from . import (
    critique_rubric,
    experiment_context_hint_template,
    manager_planning_preamble,
    pattern_library,
    tool_description_templates,
    worker_pitfalls,
)

# Mapping of canonical artifact name -> default CONTENT string.
DEFAULTS: dict[str, str] = {
    "worker_pitfalls": worker_pitfalls.CONTENT,
    "manager_planning_preamble": manager_planning_preamble.CONTENT,
    "experiment_context_hint_template": experiment_context_hint_template.CONTENT,
    "pattern_library": pattern_library.CONTENT,
    "tool_description_templates": tool_description_templates.CONTENT,
    "critique_rubric": critique_rubric.CONTENT,
}

__all__ = ["DEFAULTS"]
