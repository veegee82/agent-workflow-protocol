"""Inline LLM repair loop for dynamic tool generation.

When ``DynamicToolFactory.create_tool`` rejects a tool because of a
*repairable* failure (validation error, schema/signature mismatch,
import error with a known alternative, dry-run crash), we re-prompt
the same LLM with a tightly scoped instruction to fix only the broken
tool, instead of throwing away the whole worker iteration.

This module is intentionally tiny: it owns the repair prompt and the
``attempt_repair`` orchestration only — the actual LLM call goes
through the same ``LLMClient`` instance the worker used.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


REPAIR_SYSTEM_PROMPT = (
    "You are repairing a single failed AWP dynamic tool. "
    "Output ONLY a JSON object with the corrected tool spec — no prose. "
    "Keep the same `name` (FQN). Fix the specific error described, then "
    "double-check the handler signature matches the parameter schema."
)


def _build_repair_prompt(
    tool_spec: dict[str, Any],
    error: str,
    category: str,
    hint: str = "",
    attempt: int = 1,
) -> list[dict[str, Any]]:
    """Build the messages list for one repair attempt."""
    name = tool_spec.get("name", "?")
    description = tool_spec.get("description", "")
    parameters = tool_spec.get("parameters", {})
    code = tool_spec.get("code", "")
    required_secrets = tool_spec.get("required_secrets", [])

    fix_hints = {
        "validation": (
            "- Make sure handler signature is `def handler(*, arg1, arg2):` "
            "(keyword-only, with the leading `*`).\n"
            "- Make sure handler ends with `return {\"ok\": True, \"status\": 200, "
            "\"data\": {...}, \"error\": None}`.\n"
            "- No `print()` after the return."
        ),
        "import": (
            "- A forbidden import was used. Remove it and use the suggested "
            "alternative from the error hint (or the pre-defined `_output_dir`, "
            "`_workspace_dir`, builtin `open`).\n"
            "- Never import os, sys, subprocess, ctypes, importlib, signal, "
            "multiprocessing."
        ),
        "schema_mismatch": (
            "- Add the missing keys to `parameters.properties` (with `type` and "
            "`description`) AND list the required ones in `parameters.required`.\n"
            "- Or remove the unused kwarg from the handler. The two MUST match."
        ),
        "dry_run": (
            "- The handler crashed when called with empty/zero inputs. Add input "
            "validation OR provide safe defaults at the top of the handler.\n"
            "- Make sure the handler ALWAYS returns the dict — never raises."
        ),
    }
    fix_block = fix_hints.get(category, "")

    user_msg = f"""# Repair Required

Your tool `{name}` was REJECTED. Fix it and resend ONLY this single tool.

## Error
{error}

{('## Hint\n' + hint) if hint else ''}

## Failure category
`{category}` (repair attempt {attempt})

## How to fix
{fix_block}

## Original spec (broken)

```json
{json.dumps({
    "name": name,
    "description": description,
    "parameters": parameters,
    "required_secrets": required_secrets,
    "code": code,
}, indent=2, default=str)}
```

## Output format

Respond with EXACTLY this JSON object (no markdown fence, no prose):

```json
{{
  "name": "{name}",
  "description": "...",
  "parameters": {{ "type": "object", "properties": {{...}}, "required": [...] }},
  "code": "def handler(*, ...):\\n    ...\\n    return {{\\"ok\\": True, \\"status\\": 200, \\"data\\": {{}}, \\"error\\": None}}",
  "required_secrets": []
}}
```
"""
    return [
        {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def attempt_repair(
    *,
    llm_client: Any,
    factory: Any,
    tool_spec: dict[str, Any],
    failed_result: dict[str, Any],
    creator_agent: str,
    namespace: str,
    max_tools: int,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Try up to ``max_attempts`` LLM-driven repairs of a failed tool.

    Returns the final ``factory.create_tool`` result (success or last
    failure).  Each attempt re-runs the full validation pipeline; the
    moment one passes the registered tool is returned.
    """
    error = failed_result.get("error", "")
    category = failed_result.get("category", "validation")
    hint = failed_result.get("hint", "")
    repairable = failed_result.get("repairable", True)

    if not repairable:
        logger.info("Tool %s failure not repairable: %s", tool_spec.get("name"), category)
        return failed_result
    if llm_client is None:
        logger.info("Tool %s repair skipped: no LLM client", tool_spec.get("name"))
        return failed_result

    last_result = failed_result
    current_spec = tool_spec
    name = tool_spec.get("name", "?")

    for attempt in range(1, max_attempts + 1):
        logger.warning(
            "Tool repair attempt %d/%d for %s (category=%s)",
            attempt, max_attempts, name, category,
        )
        try:
            factory._bump("repair_attempts")
        except Exception:
            pass

        try:
            messages = _build_repair_prompt(
                current_spec, error, category, hint, attempt
            )
            fixed = llm_client.chat_json(messages, temperature=0.0)
        except Exception as exc:
            logger.warning("Repair LLM call failed: %s", exc)
            return last_result

        if not isinstance(fixed, dict) or fixed.get("_parse_failure"):
            logger.warning("Repair LLM returned unparseable response")
            return last_result

        # Force the original FQN — never let the LLM rename the tool.
        fixed["name"] = name
        new_code = fixed.get("code", "")
        new_params = fixed.get("parameters", current_spec.get("parameters", {}))
        new_secrets = fixed.get("required_secrets") or current_spec.get("required_secrets") or []
        new_desc = fixed.get("description") or current_spec.get("description", "")

        if not new_code:
            logger.warning("Repair attempt %d: LLM omitted code", attempt)
            return last_result

        retry_result = factory.create_tool(
            name=name,
            description=new_desc,
            parameters=new_params,
            code=new_code,
            creator_agent=creator_agent,
            max_tools=max_tools,
            allowed_namespace=namespace,
            required_secrets=new_secrets if new_secrets else None,
        )

        if retry_result.get("ok"):
            try:
                factory._bump("repair_successes")
            except Exception:
                pass
            retry_result["repaired"] = True
            retry_result["repair_attempts"] = attempt
            logger.info(
                "Tool %s SUCCESSFULLY repaired on attempt %d", name, attempt
            )
            return retry_result

        # Update for next attempt
        last_result = retry_result
        current_spec = {
            "name": name,
            "description": new_desc,
            "parameters": new_params,
            "code": new_code,
            "required_secrets": new_secrets,
        }
        error = retry_result.get("error", "")
        category = retry_result.get("category", category)
        hint = retry_result.get("hint", "")
        if not retry_result.get("repairable", True):
            break

    logger.warning(
        "Tool %s repair exhausted after %d attempts: %s",
        name, max_attempts, last_result.get("error", ""),
    )
    return last_result
