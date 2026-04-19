"""v0 default for the ``manager_planning_preamble`` artifact.

This is the short instructional preamble rendered directly after the PLAN
JSON schema block inside the manager system prompt. It tells the manager
that PLAN is a one-shot first-iteration decision and how progress tracking
works.
"""

from __future__ import annotations

CONTENT = (
    "Use PLAN **once** on the first iteration to decompose the problem before delegating.\n"
    "You can only PLAN once — after that, use DELEGATE to execute the plan.\n"
    "After planning, you will see a Task Plan Progress section tracking subtask status.\n"
    "Map your DELEGATE worker_ids to subtask IDs to enable automatic progress tracking.\n"
    "**IMPORTANT: Do NOT issue PLAN again after the first iteration. Use DELEGATE instead.**"
)
