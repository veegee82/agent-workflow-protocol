"""AWP Standalone Runtime -- Minimal workflow executor.

This module provides a lightweight, self-contained runtime that can
execute AWP workflows without any external agent framework.  It is
intentionally minimal and serves as:

1. A reference implementation proving AWP is truly runtime-agnostic.
2. A quick-start option for users who want to run AWP workflows
   without installing a full agent platform.

For production use, consider a full-featured AWP-compatible runtime.

Usage::

    from awp.runtime import WorkflowRunner

    runner = WorkflowRunner("path/to/my-workflow")
    result = runner.run("Analyze the latest quarterly report")
    print(result)
"""

from .runner import WorkflowRunner
from .agent import StandaloneAgent
from .tools import ToolRegistry

__all__ = ["WorkflowRunner", "StandaloneAgent", "ToolRegistry"]
