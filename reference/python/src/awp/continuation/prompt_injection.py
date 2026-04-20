"""Deterministic continuation prefix rendering.

See Plan 3 design in docs/superpowers/specs/2026-04-20-experiment-task-hierarchy-design.md §7.2–7.3.
"""

from __future__ import annotations

from .bundle_loader import BundleEntry, ContinuationBundle, ReferencePointer


class ContinuationBudgetError(Exception):
    """Raised when primary material alone exceeds the rendering budget."""


# 0.8 × 150_000 tokens × 4 chars/token ≈ 480_000.
_DEFAULT_MAX_CHARS = 480_000
_YOUR_TASK_BOILERPLATE = (
    "Produce the evolved deliverable based on the prior material and the "
    "user feedback. Do not re-derive material that is already present "
    "above; build on it. Use the reference material only if the primary "
    "material has a gap the feedback asks to fill."
)


def render_continuation_prefix(
    bundle: ContinuationBundle,
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    primary = _render_primary(bundle.primary_materials)
    footer = _render_footer(bundle.user_feedback)

    # If primary alone is over budget, refuse.
    if len(primary) + len(footer) > max_chars:
        raise ContinuationBudgetError(
            "primary material exceeds rendering budget — split the continuation "
            "task or remove non-essential primary entries"
        )

    # Try full form first.
    refs_full = _render_references(bundle.reference_paths, full=True)
    full = _assemble(primary, refs_full, footer)
    if len(full) <= max_chars:
        return full

    # Fall back to metadata-only references.
    refs_stubs = _render_references(bundle.reference_paths, full=False)
    medium = _assemble(primary, refs_stubs, footer)
    if len(medium) <= max_chars:
        return medium

    # Last resort: drop references entirely.
    return _assemble(primary, "", footer)


def _render_primary(entries: list[BundleEntry]) -> str:
    parts = ["## Continuation Context", "", "### Prior deliverable (primary)", ""]
    for e in entries:
        parts.append(f"#### {e.source_task} / {e.relative_path}")
        parts.append("")
        parts.append(e.content_text)
        parts.append("")
    return "\n".join(parts)


def _render_references(refs: list[ReferencePointer], *, full: bool) -> str:
    if not refs:
        return ""
    parts = ["### Reference material (available via fs.read)", ""]
    for r in refs:
        line = f"- {r.source_task} / {r.relative_path} ({r.size_bytes} bytes)"
        if full and r.summary_head:
            head = r.summary_head.replace("\n", " ")
            line += f" — head: {head}"
        parts.append(line)
    parts.append("")
    return "\n".join(parts)


def _render_footer(user_feedback: str) -> str:
    return (
        "## User Feedback\n\n"
        f"{user_feedback}\n\n"
        "## Your Task\n\n"
        f"{_YOUR_TASK_BOILERPLATE}\n"
    )


def _assemble(primary: str, refs: str, footer: str) -> str:
    parts = [primary]
    if refs:
        parts.append(refs)
    parts.append(footer)
    return "\n".join(parts)
