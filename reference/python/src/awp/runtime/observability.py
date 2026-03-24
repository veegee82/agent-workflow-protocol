"""AWP Observability -- File-based tracing, metrics, and audit trail.

All outputs are simple JSON/JSONL files with no external dependencies.
This is the reference implementation; production deployments can swap in
OpenTelemetry, Prometheus, or any other backend.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """File-based span tracer.  Writes JSONL to ``data/traces/{run_id}.jsonl``."""

    def __init__(
        self,
        output_dir: Path,
        run_id: str,
        config: Any = None,
    ) -> None:
        self._dir = output_dir
        self._run_id = run_id
        self._spans: dict[str, dict[str, Any]] = {}
        self._completed: list[dict[str, Any]] = []
        self._config = config

    def start_span(
        self,
        name: str,
        parent_id: Optional[str] = None,
        attributes: Optional[dict[str, Any]] = None,
    ) -> str:
        """Start a new span and return its ID."""
        span_id = uuid.uuid4().hex[:16]
        self._spans[span_id] = {
            "span_id": span_id,
            "parent_id": parent_id,
            "name": name,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "start_ts": time.monotonic(),
            "attributes": attributes or {},
        }
        return span_id

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        attributes: Optional[dict[str, Any]] = None,
    ) -> None:
        """End a span and record its duration."""
        span = self._spans.pop(span_id, None)
        if span is None:
            return
        end_ts = time.monotonic()
        duration_ms = round((end_ts - span.pop("start_ts")) * 1000, 2)
        if attributes:
            span["attributes"].update(attributes)
        span["end_time"] = datetime.now(timezone.utc).isoformat()
        span["duration_ms"] = duration_ms
        span["status"] = status
        self._completed.append(span)

    def flush(self) -> Optional[Path]:
        """Write completed spans to JSONL file."""
        if not self._completed:
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{self._run_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for span in self._completed:
                f.write(json.dumps(span, default=str) + "\n")
        count = len(self._completed)
        self._completed.clear()
        logger.info("Flushed %d trace spans to %s", count, path)
        return path


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """In-memory metrics collector.  Flushes to ``data/metrics/{run_id}.json``."""

    def __init__(
        self,
        output_dir: Path,
        run_id: str,
        config: Any = None,
    ) -> None:
        self._dir = output_dir
        self._run_id = run_id
        self._counters: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._config = config

    def increment(
        self, name: str, value: float = 1.0, labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Increment a counter metric."""
        key = self._key(name, labels)
        self._counters[key] = self._counters.get(key, 0.0) + value

    def histogram(
        self, name: str, value: float, labels: Optional[dict[str, str]] = None,
    ) -> None:
        """Record a histogram observation."""
        key = self._key(name, labels)
        self._histograms.setdefault(key, []).append(value)

    def flush(self) -> Optional[Path]:
        """Write all metrics to a JSON file."""
        if not self._counters and not self._histograms:
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{self._run_id}.json"

        data = {
            "run_id": self._run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": dict(self._counters),
            "histograms": {
                k: {
                    "count": len(v),
                    "sum": sum(v),
                    "min": min(v) if v else 0,
                    "max": max(v) if v else 0,
                    "values": v,
                }
                for k, v in self._histograms.items()
            },
        }
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        logger.info("Flushed metrics to %s", path)
        return path

    @staticmethod
    def _key(name: str, labels: Optional[dict[str, str]] = None) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# ---------------------------------------------------------------------------
# AuditTrail
# ---------------------------------------------------------------------------

class AuditTrail:
    """Append-only audit trail with hash chain integrity.

    Each entry's ``hash`` = SHA-256(prev_hash + canonical JSON of event).
    First entry uses ``prev_hash = "0" * 64``.
    """

    def __init__(
        self,
        output_dir: Path,
        run_id: str,
        config: Any = None,
    ) -> None:
        self._dir = output_dir
        self._run_id = run_id
        self._prev_hash = "0" * 64
        self._entries: list[dict[str, Any]] = []
        self._seq = 0
        self._config = config

    def record(
        self,
        event_type: str,
        agent_id: str = "",
        details: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record an audit event with hash chain integrity."""
        self._seq += 1
        event = {
            "seq": self._seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "agent_id": agent_id,
            "details": details or {},
            "prev_hash": self._prev_hash,
        }
        # Compute hash
        canonical = json.dumps(event, sort_keys=True, default=str)
        event["hash"] = hashlib.sha256(canonical.encode()).hexdigest()
        self._prev_hash = event["hash"]
        self._entries.append(event)
        return event

    def flush(self) -> Optional[Path]:
        """Write audit entries to JSONL file."""
        if not self._entries:
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{self._run_id}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry, default=str) + "\n")
        count = len(self._entries)
        self._entries.clear()
        logger.info("Flushed %d audit entries to %s", count, path)
        return path

    @staticmethod
    def verify_chain(entries: list[dict[str, Any]]) -> bool:
        """Verify the integrity of a list of audit entries."""
        prev_hash = "0" * 64
        for entry in entries:
            if entry.get("prev_hash") != prev_hash:
                return False
            # Recompute hash
            check = dict(entry)
            stored_hash = check.pop("hash")
            canonical = json.dumps(check, sort_keys=True, default=str)
            computed = hashlib.sha256(canonical.encode()).hexdigest()
            if computed != stored_hash:
                return False
            prev_hash = stored_hash
        return True


# ---------------------------------------------------------------------------
# ObservabilityContext
# ---------------------------------------------------------------------------

@dataclass
class ObservabilityContext:
    """Composed observability subsystems."""

    tracer: Optional[Tracer] = None
    metrics: Optional[MetricsCollector] = None
    audit: Optional[AuditTrail] = None

    @classmethod
    def from_config(
        cls,
        manifest: Any,
        workflow_dir: Path,
        run_id: str,
    ) -> ObservabilityContext:
        """Create context from manifest configuration."""
        tracer = None
        metrics = None
        audit = None

        obs_cfg = getattr(manifest, "observability", None)
        data_dir = workflow_dir / "data"

        # Tracing
        if obs_cfg and hasattr(obs_cfg, "tracing"):
            t_cfg = obs_cfg.tracing
            if hasattr(t_cfg, "enabled") and t_cfg.enabled:
                tracer = Tracer(data_dir / "traces", run_id, config=t_cfg)

        # Metrics
        if obs_cfg and hasattr(obs_cfg, "metrics"):
            m_cfg = obs_cfg.metrics
            if hasattr(m_cfg, "enabled") and m_cfg.enabled:
                metrics = MetricsCollector(data_dir / "metrics", run_id, config=m_cfg)

        # Audit
        if obs_cfg and hasattr(obs_cfg, "audit"):
            a_cfg = obs_cfg.audit
            if hasattr(a_cfg, "enabled") and a_cfg.enabled:
                audit = AuditTrail(data_dir / "audit", run_id, config=a_cfg)

        return cls(tracer=tracer, metrics=metrics, audit=audit)

    def flush_all(self) -> None:
        """Flush all subsystems to disk."""
        if self.tracer:
            self.tracer.flush()
        if self.metrics:
            self.metrics.flush()
        if self.audit:
            self.audit.flush()
