"""Resolver for S3 object sources."""

from __future__ import annotations

import io
import logging
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)

# Extension to format mapping
_EXTENSION_MAP: dict[str, str] = {
    ".json": "json",
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".txt": "text",
    ".npy": "npy",
}


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse ``s3://bucket/key`` into (bucket, key)."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI (must start with s3://): {uri!r}")
    without_scheme = uri[5:]
    slash = without_scheme.find("/")
    if slash < 0:
        raise ValueError(f"S3 URI must include a key: {uri!r}")
    return without_scheme[:slash], without_scheme[slash + 1:]


def _detect_format(source: Source, key: str) -> str:
    """Determine format from source hint or key extension."""
    if source.format:
        return source.format
    for ext, fmt in _EXTENSION_MAP.items():
        if key.endswith(ext):
            return fmt
    return "bytes"


def _deserialize(raw: bytes, fmt: str) -> Any:
    """Deserialize raw bytes by format."""
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
    if fmt == "npy":
        try:
            import numpy as np
            return np.load(io.BytesIO(raw), allow_pickle=False)
        except ImportError:
            raise ImportError("numpy is required to load .npy files.")
    return raw


class S3Resolver:
    """Resolve ``kind='s3'`` sources via boto3."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "s3"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 sources. Install with: pip install boto3"
            )

        bucket, key = _parse_s3_uri(source.uri)
        region = source.params.get("region")

        logger.info("Downloading s3://%s/%s", bucket, key)

        kwargs: dict[str, Any] = {}
        if region:
            kwargs["region_name"] = region

        client = boto3.client("s3", **kwargs)
        response = client.get_object(Bucket=bucket, Key=key)
        raw = response["Body"].read()

        fmt = _detect_format(source, key)
        data = _deserialize(raw, fmt)

        metadata: dict[str, Any] = {
            "source_kind": "s3",
            "bucket": bucket,
            "key": key,
            "size": len(raw),
            "format": fmt,
        }
        if region:
            metadata["region"] = region

        return ResolverResult(data=data, metadata=metadata)
