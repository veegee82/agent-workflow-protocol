"""Planning-phase validation rules (R31+).

This module is intentionally separate from ``rules.py`` so the legacy
R1–R30 file does not keep growing as planning-time invariants accumulate.

R31 — Plan-Tool-Closure
=======================

When the manager emits a PLAN decision, every subtask MUST declare a
``tool_manifest`` listing the capabilities required to execute it. Each
manifest entry MUST be of the form::

    {
      "subtask": "<subtask_id>",
      "capability": "<short capability tag>",
      "reuse_or_generate": "reuse" | "generate",
      "pattern_id": "<id from awp.patterns>"   # required iff reuse
    }

Rationale: in real delegation-loop runs the manager planned at the
*subtask* level (e.g. "fetch OHLC data") but never at the *tool* level.
Mismatches between assumed and actual API behaviour were discovered only
during worker execution, costing whole sub-delegations to repair. R31
forces the manager to confront tool-level reality during the cheap PLAN
phase, before any worker is spawned.

The check is HARD: a plan that fails R31 must be rejected and re-planned.
The runtime caller is responsible for translating the violations list
into a manager-visible feedback message.
"""

from __future__ import annotations

from typing import Any, Iterable

# We import the pattern library lazily to avoid an awp-core → awp-runtime
# import cycle (awp-core has no runtime dependency).  Resolution happens
# at call time inside ``_known_pattern_ids``.

_VALID_RG = {"reuse", "synthesize", "generate"}


def _known_pattern_ids() -> set[str]:
    try:
        from awp.patterns import PATTERNS  # type: ignore

        return set(PATTERNS.keys())
    except Exception:
        # awp-runtime not importable in this environment — fall back to
        # an empty set.  Plans that mark capabilities as `generate` are
        # unaffected; plans claiming `reuse` will fail closed, which is
        # the safer default.
        return set()


def _known_archetype_ids() -> set[str]:
    try:
        from awp.patterns import ARCHETYPES  # type: ignore

        return set(ARCHETYPES.keys())
    except Exception:
        return set()


def validate_runtime_plan(plan: dict[str, Any]) -> list[str]:
    """Validate a runtime PLAN decision against R31.

    Args:
        plan: The parsed manager output dict with ``decision == "plan"``.

    Returns:
        A list of human-readable violation strings. An empty list means
        the plan satisfies R31.
    """
    violations: list[str] = []

    if not isinstance(plan, dict):
        return ["R31: plan output must be a JSON object"]
    if plan.get("decision") != "plan":
        # R31 only applies to PLAN decisions; other decisions pass through.
        return []

    subtasks = plan.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        return ["R31: PLAN decision must include a non-empty 'subtasks' array"]

    known_patterns = _known_pattern_ids()
    known_archetypes = _known_archetype_ids()
    seen_subtask_ids: set[str] = set()

    for idx, st in enumerate(subtasks):
        if not isinstance(st, dict):
            violations.append(f"R31: subtask[{idx}] is not an object")
            continue

        sid = st.get("id") or f"subtask_{idx}"
        if sid in seen_subtask_ids:
            violations.append(f"R31: duplicate subtask id '{sid}'")
        seen_subtask_ids.add(sid)

        manifest = st.get("tool_manifest")
        if not isinstance(manifest, list) or not manifest:
            violations.append(
                f"R31: subtask '{sid}' is missing a non-empty 'tool_manifest' "
                f"(declare every capability the subtask needs, marked as "
                f"'reuse' or 'generate')"
            )
            continue

        for j, entry in enumerate(manifest):
            if not isinstance(entry, dict):
                violations.append(
                    f"R31: subtask '{sid}'.tool_manifest[{j}] is not an object"
                )
                continue
            cap = entry.get("capability")
            rg = entry.get("reuse_or_generate")
            if not isinstance(cap, str) or not cap.strip():
                violations.append(
                    f"R31: subtask '{sid}'.tool_manifest[{j}] missing string 'capability'"
                )
            if rg not in _VALID_RG:
                violations.append(
                    f"R31: subtask '{sid}'.tool_manifest[{j}].reuse_or_generate "
                    f"must be 'reuse' or 'generate' (got {rg!r})"
                )
            if rg == "reuse":
                pid = entry.get("pattern_id")
                if not isinstance(pid, str) or not pid.strip():
                    violations.append(
                        f"R31: subtask '{sid}'.tool_manifest[{j}] marks 'reuse' "
                        f"but is missing 'pattern_id'"
                    )
                elif known_patterns and pid not in known_patterns:
                    violations.append(
                        f"R31: subtask '{sid}'.tool_manifest[{j}] references "
                        f"unknown pattern_id '{pid}' (known: "
                        f"{sorted(known_patterns)})"
                    )
            elif rg == "synthesize":
                aid = entry.get("archetype_id")
                rparams = entry.get("recipe_params")
                if not isinstance(aid, str) or not aid.strip():
                    violations.append(
                        f"R31: subtask '{sid}'.tool_manifest[{j}] marks "
                        f"'synthesize' but is missing 'archetype_id'"
                    )
                elif known_archetypes and aid not in known_archetypes:
                    violations.append(
                        f"R31: subtask '{sid}'.tool_manifest[{j}] references "
                        f"unknown archetype_id '{aid}' (known: "
                        f"{sorted(known_archetypes)})"
                    )
                if not isinstance(rparams, dict) or not rparams:
                    violations.append(
                        f"R31: subtask '{sid}'.tool_manifest[{j}] marks "
                        f"'synthesize' but is missing a non-empty "
                        f"'recipe_params' object (declare the archetype's "
                        f"required params: e.g. for fetch → backend, "
                        f"url_template, inputs)"
                    )
            elif rg == "generate":
                # For generated tools the manager MUST surface its
                # assumptions about data shape, API granularity, file
                # formats, etc. so domain-quirk mismatches (e.g.
                # "CoinGecko /ohlc?days=30 returns 4-hour candles, not
                # daily") are caught at PLAN time instead of after a
                # full worker run.
                assumptions = entry.get("assumptions")
                if not isinstance(assumptions, list) or not assumptions:
                    violations.append(
                        f"R31: subtask '{sid}'.tool_manifest[{j}] marks "
                        f"'generate' but is missing a non-empty 'assumptions' "
                        f"list (declare data shape, API granularity, file "
                        f"formats, units, and any other domain quirks the "
                        f"generated tool will rely on; before generating, "
                        f"reconsider whether an existing pattern in the "
                        f"Available Patterns table fits)"
                    )
                else:
                    for ai, a in enumerate(assumptions):
                        if not isinstance(a, str) or not a.strip():
                            violations.append(
                                f"R31: subtask '{sid}'.tool_manifest[{j}]"
                                f".assumptions[{ai}] must be a non-empty string"
                            )

    return violations


def format_violations(violations: Iterable[str]) -> str:
    """Render violations as a manager-visible feedback block."""
    items = list(violations)
    if not items:
        return ""
    body = "\n".join(f"  - {v}" for v in items)
    return (
        "Your PLAN was rejected by validator rule R31 (Plan-Tool-Closure).\n"
        "Re-issue PLAN with a 'tool_manifest' on every subtask.\n"
        "Each manifest entry must be {subtask, capability, reuse_or_generate, "
        "...}. Three modes:\n"
        "  - 'reuse'      → set pattern_id to a concrete pattern\n"
        "  - 'synthesize' → set archetype_id + recipe_params (PREFERRED for new tools)\n"
        "  - 'generate'   → set assumptions list (last resort, freeform)\n"
        "Violations:\n" + body
    )


__all__ = ["validate_runtime_plan", "format_violations"]
