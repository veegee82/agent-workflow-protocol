"""Continuation loader — y-axis carry-over across tasks.

Reads a continuation task's `task.json.inputs`, resolves each `from_task`
to its prior BEST bundle, and produces a deterministic prefix for the
Manager prompt.
"""

from .bundle_loader import (
    BundleEntry,
    ContinuationBundle,
    ContinuationInputError,
    ReferencePointer,
    load_continuation_bundle,
)
from .prompt_injection import (
    ContinuationBudgetError,
    render_continuation_prefix,
)

__all__ = [
    "BundleEntry",
    "ContinuationBundle",
    "ContinuationBudgetError",
    "ContinuationInputError",
    "ReferencePointer",
    "load_continuation_bundle",
    "render_continuation_prefix",
]
