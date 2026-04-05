"""Individual scoring functions for each metric kind.

Each scorer takes the result dict, state dict, kind-specific params,
and optional dependencies, then returns a float in [0.0, 1.0].
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..llm import LLMClient

logger = logging.getLogger(__name__)


def score_deterministic_test(
    result: dict[str, Any],
    state: dict[str, Any],
    params: dict[str, Any],
) -> tuple[float, str | None]:
    """Evaluate a safe expression against the result and state.

    Params:
        expr: A Python expression string. Available names: ``result``, ``state``.

    Returns:
        (score, evidence) — 1.0 if truthy, 0.0 if falsy.
    """
    from ..expressions import safe_eval

    expr = params.get("expr", "")
    if not expr:
        return 0.0, "No 'expr' in params"

    ctx = {"result": result, "state": state}
    try:
        value = safe_eval(expr, ctx)
        passed = bool(value)
        return (1.0 if passed else 0.0), f"expr={expr!r} -> {value}"
    except Exception as exc:
        return 0.0, f"Expression error: {exc}"


def score_deterministic_assertion(
    result: dict[str, Any],
    state: dict[str, Any],
    params: dict[str, Any],
) -> tuple[float, str | None]:
    """Evaluate a list of assertion expressions, return fraction passing.

    Params:
        assertions: List of expression strings.

    Returns:
        (score, evidence) — fraction of assertions that passed.
    """
    from ..expressions import safe_eval

    assertions = params.get("assertions", [])
    if not assertions:
        return 0.0, "No 'assertions' in params"

    ctx = {"result": result, "state": state}
    passed = 0
    details: list[str] = []
    for i, assertion in enumerate(assertions):
        try:
            value = safe_eval(assertion, ctx)
            if bool(value):
                passed += 1
                details.append(f"[ok] {assertion}")
            else:
                details.append(f"[FAIL] {assertion} -> {value}")
        except Exception as exc:
            details.append(f"[ERROR] {assertion} -> {exc}")

    score = passed / len(assertions) if assertions else 0.0
    evidence = f"{passed}/{len(assertions)} passed: " + "; ".join(details)
    return score, evidence


def score_rubric_judge(
    result: dict[str, Any],
    state: dict[str, Any],
    params: dict[str, Any],
    llm_client: Optional["LLMClient"] = None,
    rubric_config: Any = None,
) -> tuple[float, str | None]:
    """LLM-based rubric judge. Sends result + rubric to LLM, parses 0-1 score.

    Params:
        rubric: Rubric text (inline or from config).

    Returns:
        (score, evidence) — LLM-assigned score and rationale.
    """
    if llm_client is None:
        return 0.0, "No LLM client available for rubric_judge"

    rubric = params.get("rubric", "")
    if not rubric and rubric_config:
        rubric = getattr(rubric_config, "rubric", "") or ""
    if not rubric:
        rubric = "Rate the output quality from 0.0 (worst) to 1.0 (best)."

    model = None
    temperature = 0.0
    if rubric_config:
        model = getattr(rubric_config, "model", None)
        temperature = getattr(rubric_config, "temperature", 0.0)

    prompt = (
        "You are an evaluation judge. Score the following result against the rubric.\n\n"
        f"## Rubric\n{rubric}\n\n"
        f"## Result\n```json\n{json.dumps(result, indent=2, default=str)[:4000]}\n```\n\n"
        "Respond with ONLY a JSON object: "
        "{\"score\": <float 0.0-1.0>, \"rationale\": \"<brief>\"}"
    )

    try:
        response = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=temperature,
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        # Handle markdown code blocks
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        parsed = json.loads(content)
        score = float(parsed.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        rationale = parsed.get("rationale", "")
        return score, f"LLM judge: {rationale}"
    except Exception as exc:
        logger.warning("rubric_judge failed: %s", exc)
        return 0.0, f"LLM judge error: {exc}"


def score_budget_utility(
    result: dict[str, Any],
    state: dict[str, Any],
    params: dict[str, Any],
    budget: Any = None,
) -> tuple[float, str | None]:
    """Score based on budget efficiency (quality relative to resource usage).

    Uses the _run_budget state key or an explicit budget object.

    Returns:
        (score, evidence) — 1.0 means very efficient, 0.0 means budget exhausted.
    """
    budget_obj = budget or state.get("_run_budget")
    if not budget_obj:
        return 1.0, "No budget info available, defaulting to 1.0"

    # Handle BudgetSnapshot (delegation loop) — has budget_fraction_remaining
    if hasattr(budget_obj, "budget_fraction_remaining"):
        score = max(0.0, min(1.0, budget_obj.budget_fraction_remaining))
        evidence = f"Budget remaining: {score:.0%}, efficiency score: {score:.2f}"
        return score, evidence

    # Handle dict from summary() or _run_budget state key
    if hasattr(budget_obj, "summary"):
        budget_info = budget_obj.summary()
    elif isinstance(budget_obj, dict):
        budget_info = budget_obj
    else:
        return 1.0, f"Unknown budget type: {type(budget_obj).__name__}"

    # Compute utilization ratio from available budget metrics
    ratios: list[float] = []
    if "tokens_used" in budget_info and "max_total_tokens" in budget_info:
        max_t = budget_info["max_total_tokens"]
        if max_t > 0:
            ratios.append(budget_info["tokens_used"] / max_t)
    if "cost_usd" in budget_info and "max_cost_usd" in budget_info:
        max_c = budget_info["max_cost_usd"]
        if max_c > 0:
            ratios.append(budget_info["cost_usd"] / max_c)
    if "wall_time_s" in budget_info and "max_wall_time" in budget_info:
        max_w = budget_info["max_wall_time"]
        if max_w > 0:
            ratios.append(budget_info["wall_time_s"] / max_w)

    if not ratios:
        return 1.0, "No measurable budget dimensions"

    avg_utilization = sum(ratios) / len(ratios)
    score = max(0.0, min(1.0, 1.0 - avg_utilization))
    evidence = f"Budget utilization: {avg_utilization:.2%}, efficiency score: {score:.2f}"
    return score, evidence


def score_policy_score(
    result: dict[str, Any],
    state: dict[str, Any],
    params: dict[str, Any],
) -> tuple[float, str | None]:
    """Check policy / governance assertions.

    Params:
        assertions: List of expression strings checking policy compliance.

    Returns:
        (score, evidence) — fraction of policy assertions passing.
    """
    from ..expressions import safe_eval

    assertions = params.get("assertions", [])
    if not assertions:
        return 1.0, "No policy assertions defined, defaulting to 1.0"

    ctx = {"result": result, "state": state}
    passed = 0
    details: list[str] = []
    for assertion in assertions:
        try:
            value = safe_eval(assertion, ctx)
            if bool(value):
                passed += 1
                details.append(f"[ok] {assertion}")
            else:
                details.append(f"[FAIL] {assertion}")
        except Exception as exc:
            details.append(f"[ERROR] {assertion} -> {exc}")

    score = passed / len(assertions) if assertions else 1.0
    evidence = f"Policy: {passed}/{len(assertions)} passed"
    if details:
        evidence += ": " + "; ".join(details)
    return score, evidence
