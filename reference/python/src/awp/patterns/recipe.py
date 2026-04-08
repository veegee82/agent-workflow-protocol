"""AWP Recipes — content-addressed, auto-learned tool instantiations.

A **recipe** binds an :class:`Archetype` to a concrete set of
parameters.  Recipes are the unit of *reuse* in the new pattern
library: instead of hand-writing one ``Pattern`` per concrete task
(``coingecko_ohlc_daily``, ``binance_ohlc_daily``, …) the runtime
captures a ``Recipe`` automatically every time it successfully
instantiates an archetype, and re-uses it on the next compatible
request.

Robustness model
================

Auto-learning is dangerous: a captured recipe is only as trustworthy
as the conditions under which it was captured.  We therefore enforce
**three trust levels** with hard gates between them:

  * ``QUARANTINED``  freshly captured. Only visible as a hint in the
                     manager prompt; never auto-instantiated.
  * ``PROBATIONARY`` passed the local replay-gate at least once. May
                     be auto-instantiated, but the repair-loop stays
                     scharf — any failure invalidates the recipe.
  * ``TRUSTED``      passed N successful replays. Direct
                     instantiation, smoke-test skipped on cache hit.

The replay-gate
---------------

Before a recipe is ever *used* (and as part of every promotion), the
runtime re-runs the recipe's stored ``smoke_input → smoke_expected``
fixture deterministically inside a fresh venv.  If the rendered
handler does not produce the recorded output bit-for-bit, the recipe
is invalidated and removed from the store.  This guarantees:

  * archetype changes (``Archetype.version`` bump) automatically
    invalidate stale recipes (the rendered code differs);
  * non-deterministic recipes never reach ``TRUSTED``;
  * a poisoned recipe cannot survive a single replay.

Persistence
-----------

Recipes live as JSON files under ``$AWP_HOME/recipes/`` (default:
``~/.awp/recipes/``).  Filenames are the recipe id (a sha256 of
``archetype_id || archetype_version || params``) so identical
captures dedupe naturally on disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .archetype import ARCHETYPES, Archetype, get_archetype

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trust levels
# ---------------------------------------------------------------------------


class TrustLevel(str, Enum):
    QUARANTINED = "quarantined"
    PROBATIONARY = "probationary"
    TRUSTED = "trusted"


# Number of consecutive successful replays required to promote.
PROMOTE_QUARANTINED_AT = 1
PROMOTE_PROBATIONARY_AT = 3


# ---------------------------------------------------------------------------
# Recipe dataclass
# ---------------------------------------------------------------------------


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_recipe_id(archetype_id: str, archetype_version: int,
                      params: dict[str, Any]) -> str:
    """Content-addressed id. Identical params dedupe automatically."""
    payload = f"{archetype_id}|v{archetype_version}|{_stable_json(params)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class Recipe:
    """A concrete instantiation of an :class:`Archetype`."""

    id: str
    archetype_id: str
    archetype_version: int
    capability: str  # short tag, e.g. "coingecko_ohlc_daily"
    description: str
    params: dict[str, Any]
    # smoke fixture used by the replay gate (input kwargs + minimal asserts)
    smoke_test: str = ""
    smoke_packages: tuple[str, ...] = field(default_factory=tuple)
    # learned-vs-seeded provenance
    source: str = "learned"  # "seeded" | "learned"
    learned_from_run: str | None = None
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trust: TrustLevel = TrustLevel.QUARANTINED
    success_count: int = 0
    failure_count: int = 0
    # legacy hand-written skeleton override (for the 6 seed recipes that
    # must remain byte-identical to their pre-archetype form). New
    # learned recipes never set this — they are rendered from the
    # archetype on demand.
    legacy_skeleton: str | None = None
    legacy_signature: dict[str, str] | None = None
    legacy_output_keys: tuple[str, ...] = field(default_factory=tuple)

    # ----- rendering -----
    def render(self) -> tuple[str, tuple[str, ...]]:
        """Return ``(handler_source, packages)`` for this recipe."""
        if self.legacy_skeleton is not None:
            return self.legacy_skeleton, tuple(self.smoke_packages)
        arch = get_archetype(self.archetype_id)
        if arch is None:
            raise RuntimeError(f"recipe {self.id} references unknown archetype {self.archetype_id!r}")
        if arch.version != self.archetype_version:
            raise RuntimeError(
                f"recipe {self.id}: archetype version mismatch "
                f"(recipe={self.archetype_version}, current={arch.version}) — invalidate"
            )
        return arch.build_skeleton(self.params)

    def signature(self) -> dict[str, str]:
        if self.legacy_signature is not None:
            return self.legacy_signature
        return dict(self.params.get("inputs", {}) or {})

    def output_keys(self) -> tuple[str, ...]:
        if self.legacy_output_keys:
            return self.legacy_output_keys
        return ("confidence",)

    # ----- promotion -----
    def record_success(self) -> None:
        self.success_count += 1
        if self.trust == TrustLevel.QUARANTINED and self.success_count >= PROMOTE_QUARANTINED_AT:
            self.trust = TrustLevel.PROBATIONARY
        elif self.trust == TrustLevel.PROBATIONARY and self.success_count >= PROMOTE_PROBATIONARY_AT:
            self.trust = TrustLevel.TRUSTED

    def record_failure(self) -> None:
        self.failure_count += 1
        # Demote on failure (one strike, you're out for trusted recipes too)
        self.trust = TrustLevel.QUARANTINED

    # ----- (de)serialisation -----
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["trust"] = self.trust.value
        d["smoke_packages"] = list(self.smoke_packages)
        d["legacy_output_keys"] = list(self.legacy_output_keys)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Recipe:
        d = dict(d)
        d["trust"] = TrustLevel(d.get("trust", "quarantined"))
        d["smoke_packages"] = tuple(d.get("smoke_packages") or ())
        d["legacy_output_keys"] = tuple(d.get("legacy_output_keys") or ())
        return cls(**d)


# ---------------------------------------------------------------------------
# Recipe store
# ---------------------------------------------------------------------------


def _default_store_path() -> Path:
    base = os.environ.get("AWP_HOME") or os.path.expanduser("~/.awp")
    return Path(base) / "recipes"


class RecipeStore:
    """File-backed recipe persistence.

    Thread-safety: not synchronised. The delegation loop runs single
    threaded per run; cross-process collisions are harmless because
    recipe files are content-addressed (identical hash → identical
    contents) and writes use ``os.replace`` for atomicity.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else _default_store_path()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover — read-only homedir
            logger.warning("RecipeStore: cannot create %s: %s", self.root, exc)
        self._cache: dict[str, Recipe] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.root.exists():
            return
        for fp in self.root.glob("*.json"):
            try:
                with fp.open("r", encoding="utf-8") as fh:
                    self._cache[fp.stem] = Recipe.from_dict(json.load(fh))
            except Exception as exc:
                logger.warning("RecipeStore: skipping unreadable %s (%s)", fp, exc)

    # ----- queries -----
    def list(self, *, min_trust: TrustLevel | None = None) -> list[Recipe]:
        self._load()
        out = list(self._cache.values())
        if min_trust:
            order = [TrustLevel.QUARANTINED, TrustLevel.PROBATIONARY, TrustLevel.TRUSTED]
            min_idx = order.index(min_trust)
            out = [r for r in out if order.index(r.trust) >= min_idx]
        return out

    def get(self, recipe_id: str) -> Recipe | None:
        self._load()
        return self._cache.get(recipe_id)

    def find_by_capability(self, capability: str) -> list[Recipe]:
        self._load()
        return [r for r in self._cache.values() if r.capability == capability]

    # ----- mutation -----
    def save(self, recipe: Recipe) -> None:
        self._load()
        self._cache[recipe.id] = recipe
        try:
            tmp = self.root / f".{recipe.id}.tmp"
            final = self.root / f"{recipe.id}.json"
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(recipe.to_dict(), fh, indent=2, sort_keys=True)
            os.replace(tmp, final)
        except OSError as exc:  # pragma: no cover
            logger.warning("RecipeStore: cannot persist %s: %s", recipe.id, exc)

    def invalidate(self, recipe_id: str, *, reason: str = "") -> None:
        self._load()
        if recipe_id in self._cache:
            logger.info("RecipeStore: invalidating recipe %s (%s)", recipe_id, reason)
            del self._cache[recipe_id]
        try:
            (self.root / f"{recipe_id}.json").unlink(missing_ok=True)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Capture API (called by dynamic_tool_factory after a successful smoke)
# ---------------------------------------------------------------------------


def capture_recipe(
    *,
    archetype_id: str,
    capability: str,
    description: str,
    params: dict[str, Any],
    smoke_test: str,
    smoke_packages: tuple[str, ...] = (),
    learned_from_run: str | None = None,
    store: RecipeStore | None = None,
) -> Recipe | None:
    """Persist a captured recipe candidate as ``QUARANTINED``.

    Returns the new (or pre-existing, on hash collision) recipe, or
    ``None`` on validation failure.  This function is intentionally
    forgiving: capture must NEVER block the foreground tool creation
    on its own failures.
    """
    arch = get_archetype(archetype_id)
    if arch is None:
        logger.warning("capture_recipe: unknown archetype %r", archetype_id)
        return None
    errs = arch.validate_params(params)
    if errs:
        logger.warning("capture_recipe: param validation failed: %s", errs)
        return None
    rid = compute_recipe_id(archetype_id, arch.version, params)
    store = store or RecipeStore()
    existing = store.get(rid)
    if existing is not None:
        existing.record_success()
        store.save(existing)
        return existing
    recipe = Recipe(
        id=rid,
        archetype_id=archetype_id,
        archetype_version=arch.version,
        capability=capability,
        description=description,
        params=params,
        smoke_test=smoke_test,
        smoke_packages=smoke_packages,
        source="learned",
        learned_from_run=learned_from_run,
        trust=TrustLevel.QUARANTINED,
    )
    store.save(recipe)
    logger.info("capture_recipe: persisted %s (capability=%s)", rid, capability)
    return recipe


# ---------------------------------------------------------------------------
# Replay gate
# ---------------------------------------------------------------------------


def replay_gate(recipe: Recipe, *, executor: Any) -> bool:
    """Re-render and re-smoke the recipe deterministically.

    ``executor`` must expose ``run_smoke(code, smoke_test, packages)``
    returning a dict ``{ok: bool, error: str}``.  Returns True iff the
    smoke passes; on failure callers should call
    :meth:`RecipeStore.invalidate`.
    """
    try:
        code, packages = recipe.render()
    except Exception as exc:
        logger.warning("replay_gate: render failed for %s: %s", recipe.id, exc)
        return False
    if not recipe.smoke_test:
        # Cannot replay without a fixture — be conservative.
        return False
    try:
        result = executor.run_smoke(
            code=code,
            smoke_test=recipe.smoke_test,
            packages=tuple(packages) + tuple(recipe.smoke_packages),
        )
    except Exception as exc:
        logger.warning("replay_gate: executor raised for %s: %s", recipe.id, exc)
        return False
    return bool(result.get("ok"))


__all__ = [
    "TrustLevel",
    "Recipe",
    "RecipeStore",
    "compute_recipe_id",
    "capture_recipe",
    "replay_gate",
]
