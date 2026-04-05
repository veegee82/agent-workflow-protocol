"""Data models for the Reflective Critique Loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Defect:
    """A single diagnosed defect in a worker result."""

    category: str  # missing_data | wrong_format | incomplete | hallucinated | stale
    location: str  # where in the output the defect is
    description: str  # what is wrong
    severity: str  # critical | warning | info


@dataclass
class CritiqueEnvelope:
    """Structured critique of a single worker result."""

    worker_id: str
    score: float  # 0.0-1.0 overall quality
    defects: list[Defect] = field(default_factory=list)
    prescriptions: list[str] = field(default_factory=list)  # concrete repair instructions
    reusable_patterns: list[str] = field(default_factory=list)  # failure patterns for other workers
    effort_estimate: str = "trivial"  # trivial | moderate | major
    summary: str = ""  # one-line summary

    @property
    def has_critical_defects(self) -> bool:
        return any(d.severity == "critical" for d in self.defects)

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.defects if d.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.defects if d.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "score": round(self.score, 4),
            "defects": [
                {
                    "category": d.category,
                    "location": d.location,
                    "description": d.description,
                    "severity": d.severity,
                }
                for d in self.defects
            ],
            "prescriptions": self.prescriptions,
            "reusable_patterns": self.reusable_patterns,
            "effort_estimate": self.effort_estimate,
            "summary": self.summary,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
        }


@dataclass
class RepairAttempt:
    """Record of a targeted repair cycle."""

    worker_id: str
    attempt: int  # 1-indexed
    original_score: float
    repaired_score: float
    defects_fixed: int
    defects_remaining: int
    critique_before: CritiqueEnvelope
    critique_after: Optional[CritiqueEnvelope] = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "worker_id": self.worker_id,
            "attempt": self.attempt,
            "original_score": round(self.original_score, 4),
            "repaired_score": round(self.repaired_score, 4),
            "defects_fixed": self.defects_fixed,
            "defects_remaining": self.defects_remaining,
        }
        if self.critique_after:
            result["critique_after"] = self.critique_after.to_dict()
        return result


@dataclass
class Pattern:
    """A recurring failure pattern observed across workers."""

    category: str
    frequency: int
    description: str
    prevention_rule: str
    first_seen_iteration: int
    last_seen_iteration: int


@dataclass
class PatternMemory:
    """Accumulated failure patterns within a single run."""

    patterns: dict[str, Pattern] = field(default_factory=dict)

    def record(self, category: str, description: str, prevention_rule: str, iteration: int) -> None:
        """Record or update a failure pattern."""
        key = category
        if key in self.patterns:
            p = self.patterns[key]
            p.frequency += 1
            p.last_seen_iteration = iteration
            # Keep the most descriptive versions
            if len(description) > len(p.description):
                p.description = description
            if len(prevention_rule) > len(p.prevention_rule):
                p.prevention_rule = prevention_rule
        else:
            self.patterns[key] = Pattern(
                category=category,
                frequency=1,
                description=description,
                prevention_rule=prevention_rule,
                first_seen_iteration=iteration,
                last_seen_iteration=iteration,
            )

    def get_prevention_rules(self) -> list[str]:
        """Return all prevention rules sorted by frequency (most common first)."""
        sorted_patterns = sorted(self.patterns.values(), key=lambda p: -p.frequency)
        return [f"[{p.category} x{p.frequency}] {p.prevention_rule}" for p in sorted_patterns]

    def has_recurring_pattern(self, category: str, min_frequency: int = 2) -> bool:
        """Check if a pattern has recurred enough to signal a systemic issue."""
        p = self.patterns.get(category)
        return p is not None and p.frequency >= min_frequency

    def to_dict(self) -> dict[str, Any]:
        return {
            k: {
                "category": p.category,
                "frequency": p.frequency,
                "description": p.description,
                "prevention_rule": p.prevention_rule,
                "first_seen": p.first_seen_iteration,
                "last_seen": p.last_seen_iteration,
            }
            for k, p in self.patterns.items()
        }
