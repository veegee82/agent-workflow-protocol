"""Resolver for generic REST API sources."""

from __future__ import annotations

import logging
import re
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)


def _substitute_secrets(headers: dict[str, str], secrets: dict[str, str]) -> dict[str, str]:
    """Replace ``$SECRET_NAME`` patterns in header values."""
    result: dict[str, str] = {}
    for k, v in headers.items():
        result[k] = re.sub(
            r"\$([A-Z_][A-Z0-9_]*)",
            lambda m: secrets.get(m.group(1), m.group(0)),
            v,
        )
    return result


def _jq_extract(data: Any, path: str) -> Any:
    """Simple JSONPath-like extraction using dot-separated keys.

    Supports paths like ``.data.items`` or ``.results[0].name``.
    This is a lightweight implementation with no external dependencies.
    """
    if not path or path == ".":
        return data

    # Strip leading dot
    path = path.lstrip(".")
    current = data

    for part in path.split("."):
        if not part:
            continue

        # Handle array index: key[0]
        bracket = part.find("[")
        if bracket >= 0:
            key = part[:bracket]
            idx_str = part[bracket + 1 : part.index("]")]
            idx = int(idx_str)
            if key:
                current = current[key]
            current = current[idx]
        else:
            current = current[part]

    return current


class ApiResolver:
    """Resolve ``kind='api'`` sources via HTTP with full method support."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "api"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        import httpx

        secrets = secrets or {}
        method: str = source.params.get("method", "GET").upper()
        headers: dict[str, str] = source.params.get("headers", {})
        body: Any = source.params.get("body")
        # Support both "jq" and "extract" param names
        jq_path: str | None = source.params.get("jq") or source.params.get("extract")

        if headers:
            headers = _substitute_secrets(headers, secrets)

        logger.info("%s %s", method, source.uri)

        with httpx.Client(timeout=source.timeout, follow_redirects=True) as client:
            req_kwargs: dict[str, Any] = {}
            if headers:
                req_kwargs["headers"] = headers

            # Attach body
            if body is not None:
                if isinstance(body, dict):
                    req_kwargs["json"] = body
                else:
                    req_kwargs["content"] = body

            response = client.request(method, source.uri, **req_kwargs)
        response.raise_for_status()

        # Deserialize
        content_type = response.headers.get("content-type", "")
        fmt = source.format or "json"

        if fmt == "json":
            try:
                data = response.json()
            except Exception:
                data = response.text
        elif fmt == "text":
            data = response.text
        else:
            data = response.content

        # Apply jq extraction
        if jq_path and isinstance(data, (dict, list)):
            try:
                data = _jq_extract(data, jq_path)
            except (KeyError, IndexError, TypeError) as exc:
                logger.warning("jq extraction '%s' failed: %s", jq_path, exc)

        metadata: dict[str, Any] = {
            "source_kind": "api",
            "status_code": response.status_code,
            "content_type": content_type,
            "method": method,
            "url": source.uri,
            "format": fmt,
        }
        return ResolverResult(data=data, metadata=metadata)
