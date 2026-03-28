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
from .delegation_loop_runner import DelegationLoopRunner
from .tools import ToolRegistry
from .observability import ObservabilityContext, Tracer, MetricsCollector, AuditTrail
from .security import SecurityContext, CircuitBreaker, RateLimiter, AccessController
from .message_bus import MessageBus
from .base_executor import BaseExecutor
from .code_executor import CodeExecutor
from .docker_executor import DockerExecutor
from .venv_executor import VenvExecutor
from .executor_factory import create_executor
from .state_persistence import StatePersistence
from .expressions import safe_eval

__all__ = [
    "WorkflowRunner",
    "StandaloneAgent",
    "DelegationLoopRunner",
    "ToolRegistry",
    "ObservabilityContext",
    "Tracer",
    "MetricsCollector",
    "AuditTrail",
    "SecurityContext",
    "CircuitBreaker",
    "RateLimiter",
    "AccessController",
    "MessageBus",
    "BaseExecutor",
    "CodeExecutor",
    "DockerExecutor",
    "VenvExecutor",
    "create_executor",
    "StatePersistence",
    "safe_eval",
]
