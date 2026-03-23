"""Template variable resolution for AWP YAML files.

Resolves {{variable}} placeholders in YAML values using a context dict.
Supports nested access like {{workflow.settings.custom.domain}}.
"""

from __future__ import annotations

import re
from typing import Any


_TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def _resolve_dotted(key: str, context: dict[str, Any]) -> Any:
    """Resolve a dotted key path like 'workflow.settings.custom.domain'."""
    parts = key.strip().split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def resolve_templates(data: Any, context: dict[str, Any]) -> Any:
    """Recursively resolve {{variable}} templates in a data structure.

    Args:
        data: YAML-loaded data (dict, list, or scalar).
        context: Variable context for resolution.

    Returns:
        Data with all templates resolved.
    """
    if isinstance(data, str):
        return _resolve_string(data, context)
    if isinstance(data, dict):
        return {k: resolve_templates(v, context) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_templates(item, context) for item in data]
    return data


def _resolve_string(s: str, context: dict[str, Any]) -> Any:
    """Resolve templates in a single string value."""
    # If the entire string is a single template, return the raw value (preserves type)
    match = _TEMPLATE_PATTERN.fullmatch(s)
    if match:
        resolved = _resolve_dotted(match.group(1), context)
        return resolved if resolved is not None else s

    # Otherwise, substitute within the string
    def replacer(m: re.Match) -> str:
        val = _resolve_dotted(m.group(1), context)
        return str(val) if val is not None else m.group(0)

    return _TEMPLATE_PATTERN.sub(replacer, s)
