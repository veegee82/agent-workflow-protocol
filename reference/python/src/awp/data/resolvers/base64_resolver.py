"""Resolver for base64-encoded inline data sources."""

from __future__ import annotations

import base64
import logging
import tempfile
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = frozenset({
    "png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "webp", "svg", "ico",
})


class Base64Resolver:
    """Resolve ``kind='base64'`` sources by decoding inline base64 data."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "base64"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        raw = base64.b64decode(source.uri)
        fmt = source.format or "bytes"

        logger.info("Decoded %d bytes of base64 data (format=%s)", len(raw), fmt)

        if fmt == "text":
            data: Any = raw.decode("utf-8", errors="replace")
        elif fmt in _IMAGE_EXTENSIONS:
            # Write to a temp file for image formats
            suffix = f".{fmt}"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(raw)
            tmp.close()
            data = tmp.name
            logger.info("Wrote base64 image to temp file: %s", data)
        else:
            data = raw

        metadata: dict[str, Any] = {
            "source_kind": "base64",
            "size": len(raw),
            "format": fmt,
        }
        if fmt in _IMAGE_EXTENSIONS:
            metadata["temp_path"] = data

        return ResolverResult(data=data, metadata=metadata)
