"""Hierarchical Context Digest (HCD).

Per-iteration compact summary of a manager run, designed to keep deep
delegation graphs (depth >=3) under control without losing context.

Each :class:`Digest` captures the run's goal, accumulated key facts,
open questions, a confidence trend, and the SHA-256 hashes of any
child-manager digests merged in during this iteration. Content is
addressed by SHA (:class:`DigestStore`), so a manager at depth N only
needs to carry the SHA of its direct children's digests in its own
digest — deeper layers can be fetched on demand via the
``digest.fetch`` tool.

The v1 generation path is **deterministic**: no LLM call. The facts
and questions come directly from worker output fields. This keeps
digests cheap, reproducible, and safe to run inside a budget-bounded
loop. An LLM mode is reserved for v2.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import fcntl  # type: ignore

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - Windows fallback
    _HAS_FCNTL = False


# Run-scoped binding for the `digest.fetch` tool.
current_digest_store: ContextVar[Optional["DigestStore"]] = ContextVar(
    "current_digest_store", default=None
)


@dataclass
class Digest:
    """Compact, content-addressable snapshot of a manager iteration."""

    goal: str = ""
    open_questions: list[str] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    confidence_trend: list[float] = field(default_factory=list)
    child_digest_hashes: list[str] = field(default_factory=list)
    iteration: int = 0
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        """Stable, human-readable rendering for prompt injection."""
        lines: list[str] = []
        lines.append(f"- goal: {self.goal or '(unspecified)'}")
        lines.append(f"- iteration: {self.iteration}")
        if self.confidence_trend:
            trend = ", ".join(f"{c:.2f}" for c in self.confidence_trend)
            lines.append(f"- confidence_trend: [{trend}]")
        else:
            lines.append("- confidence_trend: []")
        if self.key_facts:
            lines.append("- key_facts:")
            for kf in self.key_facts:
                lines.append(f"  * {kf}")
        else:
            lines.append("- key_facts: (none)")
        if self.open_questions:
            lines.append("- open_questions:")
            for q in self.open_questions:
                lines.append(f"  * {q}")
        else:
            lines.append("- open_questions: (none)")
        if self.child_digest_hashes:
            lines.append("- child_digest_hashes:")
            for h in self.child_digest_hashes:
                lines.append(f"  * {h}")
        return "\n".join(lines)


class DigestStore:
    """Content-addressed JSON storage for :class:`Digest` records.

    One store per manager run. Files live at
    ``<workspace>/digest/<sha>.json``. Writes are serialised with an
    advisory flock so two workers in the same run can't corrupt a
    record.
    """

    def __init__(self, workspace: Path) -> None:
        self._dir = Path(workspace) / "digest"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._dir

    def path_for(self, sha: str) -> Path:
        return self._dir / f"{sha}.json"

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def put(self, digest: Digest) -> str:
        """Persist ``digest`` and return its SHA-256 hash."""
        payload = digest.to_dict()
        sha = self._hash(payload)
        target = self.path_for(sha)
        with self._lock:
            if target.exists():
                return sha  # deterministic: same content -> same sha
            tmp = target.with_suffix(".json.tmp")
            with open(tmp, "wb") as fh:
                if _HAS_FCNTL:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                    except OSError:
                        pass
                try:
                    fh.write(
                        json.dumps(
                            payload, indent=2, sort_keys=True, ensure_ascii=False
                        ).encode("utf-8")
                    )
                    fh.flush()
                finally:
                    if _HAS_FCNTL:
                        try:
                            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        except OSError:
                            pass
            tmp.replace(target)
        return sha

    def get(self, sha: str) -> Optional[Digest]:
        target = self.path_for(sha)
        if not target.exists():
            return None
        try:
            with open(target, "rb") as fh:
                payload = json.loads(fh.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("DigestStore.get(%s) failed: %s", sha, exc)
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return Digest(
                goal=str(payload.get("goal", "")),
                open_questions=list(payload.get("open_questions") or []),
                key_facts=list(payload.get("key_facts") or []),
                confidence_trend=[float(x) for x in (payload.get("confidence_trend") or [])],
                child_digest_hashes=list(payload.get("child_digest_hashes") or []),
                iteration=int(payload.get("iteration") or 0),
                run_id=str(payload.get("run_id", "")),
            )
        except (TypeError, ValueError) as exc:
            logger.debug("DigestStore.get(%s) decode failed: %s", sha, exc)
            return None


# ----------------------------------------------------------------------
# Deterministic digest generation
# ----------------------------------------------------------------------


_KEY_FACT_FIELDS: tuple[str, ...] = (
    "summary",
    "result",
    "findings",
    "analysis",
    "answer",
    "output",
)

_OPEN_QUESTIONS_FIELDS: tuple[str, ...] = (
    "open_questions",
    "questions",
    "blockers",
    "unknowns",
)

_KEY_FACT_CONFIDENCE_THRESHOLD: float = 0.8
_OPEN_QUESTION_CONFIDENCE_THRESHOLD: float = 0.7
_KEY_FACT_CAP: int = 10
_OPEN_QUESTION_CAP: int = 10


def _coerce_text(value: Any, limit: int = 240) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
    elif isinstance(value, (int, float, bool)):
        s = str(value)
    elif isinstance(value, (list, dict)):
        try:
            s = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            s = str(value)
    else:
        s = str(value)
    s = s.strip()
    if not s:
        return None
    if len(s) > limit:
        s = s[: limit - 3] + "..."
    return s


def _confidence_of(result: dict) -> float:
    try:
        val = result.get("confidence")
        if isinstance(val, (int, float)):
            return float(val)
    except Exception:
        pass
    return 0.0


def build_digest_from_iteration(
    history_entry: dict[str, Any],
    prior_digest: Optional[Digest],
    run_id: str,
    iteration: int,
    delegation_results: Optional[list[dict]] = None,
    original_task: Optional[str] = None,
) -> Digest:
    """Build a :class:`Digest` deterministically from one iteration.

    Parameters
    ----------
    history_entry:
        The entry appended to ``runner._history`` for this iteration. May
        carry ``confidence``, ``key_findings``, and ``validation``.
    prior_digest:
        The previous iteration's digest (or ``None`` on the first pass).
        Its ``goal`` and ``key_facts`` are carried forward; its
        ``confidence_trend`` is extended.
    run_id:
        Manager run id of the current runner.
    iteration:
        Iteration number (1-based).
    delegation_results:
        Raw worker-result list for this iteration. Used to extract
        key_facts (confidence >= 0.8) and open_questions (< 0.7).
    original_task:
        The manager's original task string; used as fallback ``goal``.
    """

    history_entry = history_entry or {}
    delegation_results = list(delegation_results or [])

    # --- goal ---
    goal = ""
    if prior_digest and prior_digest.goal:
        goal = prior_digest.goal
    elif original_task:
        coerced = _coerce_text(original_task, limit=500)
        if coerced:
            goal = coerced

    # --- key facts ---
    key_facts: list[str] = list(prior_digest.key_facts) if prior_digest else []
    for dr in delegation_results:
        if not isinstance(dr, dict):
            continue
        wid = dr.get("worker_id", "?")
        result = dr.get("result", {}) if isinstance(dr.get("result"), dict) else {}
        conf = _confidence_of(result)
        if conf < _KEY_FACT_CONFIDENCE_THRESHOLD:
            continue
        for key in _KEY_FACT_FIELDS:
            if key in result:
                text = _coerce_text(result[key])
                if text:
                    key_facts.append(f"{wid}: {text}")
                break
    # Dedupe while preserving order, then cap.
    seen: set[str] = set()
    deduped: list[str] = []
    for kf in key_facts:
        if kf in seen:
            continue
        seen.add(kf)
        deduped.append(kf)
    key_facts = deduped[-_KEY_FACT_CAP:]

    # --- open questions ---
    open_questions: list[str] = []
    for dr in delegation_results:
        if not isinstance(dr, dict):
            continue
        wid = dr.get("worker_id", "?")
        result = dr.get("result", {}) if isinstance(dr.get("result"), dict) else {}
        conf = _confidence_of(result)
        # Explicit open_questions field: always surface (whatever confidence).
        for key in _OPEN_QUESTIONS_FIELDS:
            val = result.get(key)
            if isinstance(val, list):
                for item in val:
                    text = _coerce_text(item)
                    if text:
                        open_questions.append(f"{wid}: {text}")
            elif isinstance(val, str):
                text = _coerce_text(val)
                if text:
                    open_questions.append(f"{wid}: {text}")
        # Low-confidence workers with no explicit questions: add a generic marker.
        if conf > 0.0 and conf < _OPEN_QUESTION_CONFIDENCE_THRESHOLD:
            # Prefer their summary field as the question stub.
            stub = None
            for key in _KEY_FACT_FIELDS:
                if key in result:
                    stub = _coerce_text(result[key], limit=160)
                    if stub:
                        break
            if stub:
                open_questions.append(f"{wid} (low confidence={conf:.2f}): {stub}")
            else:
                open_questions.append(f"{wid} low confidence={conf:.2f}")
    # Dedupe + cap.
    seen2: set[str] = set()
    dq: list[str] = []
    for q in open_questions:
        if q in seen2:
            continue
        seen2.add(q)
        dq.append(q)
    open_questions = dq[:_OPEN_QUESTION_CAP]

    # --- confidence trend ---
    trend: list[float] = list(prior_digest.confidence_trend) if prior_digest else []
    conf_entry = history_entry.get("confidence")
    if isinstance(conf_entry, (int, float)):
        trend.append(float(conf_entry))

    return Digest(
        goal=goal,
        open_questions=sorted(set(open_questions)) if False else open_questions,
        key_facts=key_facts,
        confidence_trend=trend,
        child_digest_hashes=[],
        iteration=iteration,
        run_id=run_id,
    )


__all__ = [
    "Digest",
    "DigestStore",
    "build_digest_from_iteration",
    "current_digest_store",
]
