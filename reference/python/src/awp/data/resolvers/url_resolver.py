"""Resolver for HTTP/HTTPS URL sources."""

from __future__ import annotations

import io
import logging
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)

# Content-Type to format mapping
_CONTENT_TYPE_MAP: dict[str, str] = {
    "application/json": "json",
    "text/csv": "csv",
    "application/csv": "csv",
    "application/octet-stream": "bytes",
    "application/parquet": "parquet",
    "application/x-parquet": "parquet",
}

# Extension to format mapping
_EXTENSION_MAP: dict[str, str] = {
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".txt": "text",
    ".html": "text",
    ".xml": "text",
}


def _substitute_secrets(headers: dict[str, str], secrets: dict[str, str]) -> dict[str, str]:
    """Replace ``$SECRET_NAME`` patterns in header values."""
    import re

    result: dict[str, str] = {}
    for k, v in headers.items():
        result[k] = re.sub(
            r"\$([A-Z_][A-Z0-9_]*)",
            lambda m: secrets.get(m.group(1), m.group(0)),
            v,
        )
    return result


def _detect_format(source: Source, content_type: str | None, url: str) -> str:
    """Determine the deserialization format from hints, Content-Type, or URL extension."""
    if source.format:
        return source.format

    # Try Content-Type (skip generic octet-stream — fall through to URL extension)
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _CONTENT_TYPE_MAP and ct != "application/octet-stream":
            return _CONTENT_TYPE_MAP[ct]

    # Try URL extension
    from urllib.parse import urlparse

    path = urlparse(url).path
    for ext, fmt in _EXTENSION_MAP.items():
        if path.endswith(ext):
            return fmt

    return "bytes"


def _deserialize(raw: bytes, fmt: str) -> Any:
    """Deserialize raw bytes according to *fmt*."""
    if fmt == "json":
        import json
        return json.loads(raw)
    if fmt == "csv":
        try:
            import pandas as pd
            return pd.read_csv(io.BytesIO(raw))
        except ImportError:
            return raw.decode("utf-8", errors="replace")
    if fmt == "parquet":
        try:
            import pandas as pd
            return pd.read_parquet(io.BytesIO(raw))
        except ImportError:
            raise ImportError(
                "pandas is required to deserialize parquet files. "
                "Install with: pip install pandas pyarrow"
            )
    if fmt == "text":
        return raw.decode("utf-8", errors="replace")
    return raw


class UrlResolver:
    """Resolve ``kind='url'`` sources via HTTP GET."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "url"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        import httpx

        secrets = secrets or {}
        headers = source.params.get("headers", {})
        if headers:
            headers = _substitute_secrets(headers, secrets)

        logger.info("Fetching URL: %s", source.uri)
        with httpx.Client(timeout=source.timeout, follow_redirects=True) as client:
            response = client.get(source.uri, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get("content-type")
        fmt = _detect_format(source, content_type, source.uri)
        data = _deserialize(response.content, fmt)

        metadata: dict[str, Any] = {
            "source_kind": "url",
            "status_code": response.status_code,
            "content_type": content_type,
            "content_length": len(response.content),
            "format": fmt,
            "url": source.uri,
        }
        return ResolverResult(data=data, metadata=metadata)
