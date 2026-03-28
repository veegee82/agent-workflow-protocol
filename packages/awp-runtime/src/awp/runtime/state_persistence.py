"""AWP State Persistence -- JSON-based state snapshots.

Saves per-agent checkpoints and a final state snapshot to disk.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StatePersistence:
    """JSON-based state persistence to ``data/state/``."""

    def __init__(self, output_dir: Path, config: Any = None) -> None:
        self._dir = output_dir
        self._config = config

    def save_checkpoint(self, agent_id: str, state: dict[str, Any]) -> Path:
        """Save a per-agent state checkpoint."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{agent_id}.json"
        data = {
            "agent_id": agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": self._make_serializable(state),
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.debug("State checkpoint saved: %s", path)
        return path

    def save_final(self, state: dict[str, Any]) -> Path:
        """Save the final workflow state."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / "final.json"
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": self._make_serializable(state),
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("Final state saved: %s", path)
        return path

    def load_checkpoint(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Load a previously saved checkpoint."""
        path = self._dir / f"{agent_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("state")

    def load_final(self) -> Optional[dict[str, Any]]:
        """Load the final state from a previous run."""
        path = self._dir / "final.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("state")

    @staticmethod
    def _make_serializable(obj: Any) -> Any:
        """Make an object JSON-serializable."""
        if isinstance(obj, dict):
            return {k: StatePersistence._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [StatePersistence._make_serializable(v) for v in obj]
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        return str(obj)
