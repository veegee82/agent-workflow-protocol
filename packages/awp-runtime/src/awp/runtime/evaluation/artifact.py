"""Evaluation artifact writer — persists eval results as JSON."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import EvalArtifact, StepEvalRecord

logger = logging.getLogger(__name__)


class EvalArtifactWriter:
    """Collects evaluation records and flushes them to a JSON file."""

    def __init__(self, output_dir: Path, run_id: str) -> None:
        self._output_dir = output_dir
        self._run_id = run_id
        self._artifact = EvalArtifact(run_id=run_id)

    def record_step(self, record: StepEvalRecord) -> None:
        """Add a step evaluation record."""
        if record.timestamp is None:
            record.timestamp = datetime.now(timezone.utc).isoformat()
        self._artifact.step_records.append(record)

    def set_final(
        self,
        score: float,
        action: str,
        result: Optional[object] = None,
        retries_used: int = 0,
    ) -> None:
        """Set the final evaluation outcome."""
        self._artifact.final_score = score
        self._artifact.final_action = action
        self._artifact.final_result = result  # type: ignore[assignment]
        self._artifact.retries_used = retries_used

    def flush(self) -> Optional[Path]:
        """Write the artifact to disk. Returns the file path or None on error."""
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            path = self._output_dir / f"{self._run_id}.json"
            data = asdict(self._artifact)
            path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            logger.info("Evaluation artifact written to %s", path)
            return path
        except Exception as exc:
            logger.warning("Failed to write evaluation artifact: %s", exc)
            return None
