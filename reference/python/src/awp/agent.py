"""AWP Agent -- Platform-agnostic abstract interface.

This module defines the minimal contract that every AWP-compliant agent
implementation MUST fulfill. Platform-specific runtimes extend this
interface with their own capabilities.

Example usage::

    from awp.agent import AWPAgent

    class MyAgent(AWPAgent):
        @property
        def name(self) -> str:
            return "researcher"

        def run(self, task: str, state: dict) -> dict:
            # ... agent logic ...
            return {self.name: {"result": "...", "confidence": 0.9}}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class AWPAgent(ABC):
    """Minimal AWP agent contract.

    Every AWP-compliant platform MUST provide a BaseAgent class that
    implements this interface.  The interface is deliberately small to
    maximize portability across runtimes.

    Required methods:
        name: Unique agent identifier matching ``identity.id`` in
              ``agent.awp.yaml``.
        run:  Execute the agent and return results.

    The return value of ``run`` MUST be a dict with at least one key
    equal to ``self.name``, whose value is the agent's result dict.
    That result dict MUST contain a ``confidence`` field (float, 0.0-1.0)
    per AWP validation rule R17.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier in the workflow DAG.

        MUST match the ``identity.id`` field in the agent's
        ``agent.awp.yaml`` configuration file.
        """

    @abstractmethod
    def run(self, task: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent.

        Args:
            task: Human-readable task description or instruction.
            state: Shared workflow state dictionary.  Contains outputs
                   from previously executed agents (keyed by agent name)
                   and any auto-injected fields from the manifest.

        Returns:
            A dict with at minimum ``{self.name: result_dict}``.
            ``result_dict`` MUST include a ``confidence`` field
            (number, 0.0--1.0).  Additional top-level keys MAY be
            included for metadata or logging.
        """
