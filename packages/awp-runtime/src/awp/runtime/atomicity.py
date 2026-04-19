"""Deterministic atomicity score for pending subtasks.

This module implements AWP Framework-Fix gamma: a pure, deterministic,
LLM-free heuristic that scores each pending subtask on a 0..1 axis where

  * 1.0 means "atomic — prefer a single flat ephemeral worker", and
  * 0.0 means "composite — a sub-manager + further decomposition is
    likely warranted".

The score is **advisory only**. It is injected into the manager planning
prompt as a hint the model can weigh alongside its own reasoning. The
runtime MUST NOT use the score to block or override a manager decision:
that would violate AWP's A3/A4 autonomy semantics (the manager is the
authority on delegation shape). See CLAUDE.md, "Architect's eye" lens.

The formula is an explicit, documented heuristic — not a law:

    z = ( a_1 * atomic_keyword_count
        - a_2 * composition_keyword_count
        - a_3 * required_outputs_count
        - a_4 * numbered_steps_count
        - a_5 * log(1 + description_length_in_words)
        + b )
    atomicity = sigmoid(z)

Constants are tuned so that:

  * "Read README.md and count its words."
      -> atomic_keyword_count = 2 ("read", "count"), no composition
         keywords, 0 explicit outputs, 0 numbered steps,
         ~6 words -> z clearly positive -> score >= 0.80.

  * A long description mentioning "coordinate", "orchestrate",
    "assemble", "synthesize" with 10 required output files
      -> composition penalty + outputs penalty + length penalty
         drive z sharply negative -> score <= 0.30.

Edge cases: missing / empty / None inputs collapse to a neutral ~0.5
(z == 0 before bias). The bias ``b`` is small and positive (0.3) so
that a completely empty subtask is slightly biased toward "atomic" —
the safer, cheaper default when the signal is absent.
"""

from __future__ import annotations

import math
import re
from typing import Any

# -- Keyword vocabularies (lowercase, whole-word matching) --------------------

# Words that suggest the subtask is itself composite and coordinates
# multiple moving parts. A sub-manager may be warranted.
COMPOSITION_KEYWORDS: frozenset[str] = frozenset(
    {
        "plan",
        "coordinate",
        "orchestrate",
        "delegate",
        "assemble",
        "synthesize",
        "integrate",
    }
)

# Words that suggest a single, well-scoped action. A flat ephemeral
# worker is usually sufficient.
ATOMIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "read",
        "compute",
        "compile",
        "verify",
        "count",
        "parse",
        "validate",
        "render",
        "extract",
    }
)

# -- Tuned constants ----------------------------------------------------------
# These are heuristic weights, NOT a law. They are calibrated against the
# two canonical examples documented in the module docstring. If you retune
# them, update the unit tests in ``tests/test_atomicity.py`` so future
# regressions are caught.
A_ATOMIC = 1.05  # per atomic keyword match
A_COMPOSITION = 1.20  # per composition keyword match
A_REQUIRED_OUTPUTS = 0.45  # per declared required_output file
A_NUMBERED_STEPS = 0.55  # per numbered / bulleted step in the description
A_LENGTH = 0.35  # multiplier on log(1 + word_count)
BIAS = 0.35  # slight bias toward "atomic" when signal is absent


# -- Helpers ------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']*")

# Numbered step markers: "1.", "1)", "Step 1", "- ", "* ". We count the
# number of *distinct* list-item markers in the description as a proxy
# for explicit procedural decomposition. Kept conservative to avoid
# double-counting prose with incidental digits.
_NUMBERED_STEP_RE = re.compile(
    r"(?m)^\s*(?:\d+[.)]|[-*]\s|step\s*\d+\b)",
    re.IGNORECASE,
)


def _sigmoid(z: float) -> float:
    # Clamp to avoid overflow in math.exp for extreme inputs.
    if z > 50:
        return 1.0
    if z < -50:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _as_dict(subtask: Any) -> dict[str, Any]:
    """Coerce ``subtask`` to a dict-like view.

    Accepts either a plain dict (the runtime representation in
    ``TaskPlan._subtasks``) or a Pydantic model / object exposing the
    same attribute names. Never raises — returns an empty dict if the
    input is unrecognisable so the score function can degrade to the
    neutral bias.
    """
    if subtask is None:
        return {}
    if isinstance(subtask, dict):
        return subtask
    # Pydantic v2
    for attr in ("model_dump", "dict"):
        if hasattr(subtask, attr):
            try:
                dumped = getattr(subtask, attr)()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
    # Fallback: read known attributes directly.
    out: dict[str, Any] = {}
    for field in ("id", "description", "required_outputs", "success_criteria"):
        if hasattr(subtask, field):
            try:
                out[field] = getattr(subtask, field)
            except Exception:
                continue
    return out


def _keyword_count(words: list[str], vocab: frozenset[str]) -> int:
    if not words:
        return 0
    # Count matches of lowercase tokens against the vocabulary. Each
    # occurrence counts; density is bounded implicitly by description
    # length and the sigmoid.
    return sum(1 for w in words if w.lower() in vocab)


def atomicity_score(subtask: Any) -> float:
    """Return the advisory atomicity score for a subtask.

    Args:
        subtask: Dict or Pydantic-like object with the usual subtask
            shape (``description``, ``required_outputs``,
            ``success_criteria``). Missing fields are tolerated.

    Returns:
        A float in [0.0, 1.0]. Higher = more atomic (prefer flat
        ephemeral worker). Lower = more composite (sub-manager may be
        warranted). Neutral ~0.5 on empty input.
    """
    data = _as_dict(subtask)

    description = str(data.get("description") or "")
    success_criteria = str(data.get("success_criteria") or "")
    # Pool description + success_criteria for keyword scanning — both
    # surfaces carry task intent; success_criteria often contains action
    # verbs too ("verify that the report exists").
    text = f"{description}\n{success_criteria}"

    words = _WORD_RE.findall(text)
    word_count = len(description.split())  # word_count uses description only

    atomic_kw = _keyword_count(words, ATOMIC_KEYWORDS)
    composition_kw = _keyword_count(words, COMPOSITION_KEYWORDS)

    required_outputs = data.get("required_outputs") or []
    if isinstance(required_outputs, (str, bytes)):
        required_outputs_count = 1 if required_outputs else 0
    else:
        try:
            required_outputs_count = len(required_outputs)
        except TypeError:
            required_outputs_count = 0

    numbered_steps = len(_NUMBERED_STEP_RE.findall(description))

    # Length term: log(1 + N) so a handful of words barely moves the
    # score, but a 200-word spec meaningfully pulls it down.
    length_term = math.log1p(max(0, word_count))

    z = (
        A_ATOMIC * atomic_kw
        - A_COMPOSITION * composition_kw
        - A_REQUIRED_OUTPUTS * required_outputs_count
        - A_NUMBERED_STEPS * numbered_steps
        - A_LENGTH * length_term
        + BIAS
    )

    score = _sigmoid(z)
    # Final safety clamp (defensive — _sigmoid already guarantees [0,1]).
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score


def atomicity_advisory_line(subtask: Any) -> str:
    """Render the advisory line shown to the manager.

    The wording is deliberately soft: the score is a hint, not a gate.
    """
    score = atomicity_score(subtask)
    if score >= 0.65:
        guidance = (
            "high -> prefer flat ephemeral worker; "
            "sub-manager only if decomposition is truly needed"
        )
    elif score <= 0.35:
        guidance = "low -> sub-manager + further decomposition is likely warranted"
    else:
        guidance = "mid -> either shape is defensible; pick the simpler one if in doubt"
    return f"Subtask atomicity score: {score:.2f} ({guidance})"


__all__ = [
    "atomicity_score",
    "atomicity_advisory_line",
    "ATOMIC_KEYWORDS",
    "COMPOSITION_KEYWORDS",
]
