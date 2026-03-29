"""Universal data source descriptor and resolver registry.

A ``Source`` is a frozen, serializable descriptor that tells the runtime
*where* data lives and *how* to fetch it.  ``SourceResolver`` implementations
handle the actual I/O for each ``kind`` of source.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source descriptor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    """Immutable descriptor for a data source.

    Use the factory classmethods (``Source.url()``, ``Source.sql()``, etc.)
    for ergonomic construction.
    """

    kind: str
    uri: str
    params: dict[str, Any] = field(default_factory=dict)
    cache: bool = True
    retries: int = 2
    timeout: float = 30.0
    format: str | None = None

    def __hash__(self) -> int:
        """Custom hash that handles unhashable ``params`` dict."""
        import json
        params_key = json.dumps(self.params, sort_keys=True, default=str) if self.params else ""
        return hash((
            self.kind,
            self.uri,
            params_key,
            self.cache,
            self.retries,
            self.timeout,
            self.format,
        ))

    # -- Factory classmethods ------------------------------------------------

    @classmethod
    def url(
        cls,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        format: str | None = None,
        cache: bool = True,
        retries: int = 2,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> Source:
        """Create an HTTP/HTTPS URL source."""
        params: dict[str, Any] = {}
        if headers:
            params["headers"] = headers
        if format:
            params["format"] = format
        params.update(kwargs)
        return cls(
            kind="url",
            uri=url,
            params=params,
            cache=cache,
            retries=retries,
            timeout=timeout,
            format=format,
        )

    @classmethod
    def sql(
        cls,
        query: str,
        *,
        dsn: str,
        params: dict[str, Any] | None = None,
        format: str = "dataframe",
        cache: bool = True,
        timeout: float = 30.0,
    ) -> Source:
        """Create a SQL query source."""
        p: dict[str, Any] = {"dsn": dsn}
        if params:
            p["query_params"] = params
        return cls(
            kind="sql",
            uri=query,
            params=p,
            cache=cache,
            retries=0,
            timeout=timeout,
            format=format,
        )

    @classmethod
    def s3(
        cls,
        uri: str,
        *,
        region: str | None = None,
        format: str | None = None,
        cache: bool = True,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> Source:
        """Create an S3 object source (``s3://bucket/key``)."""
        params: dict[str, Any] = {}
        if region:
            params["region"] = region
        params.update(kwargs)
        return cls(
            kind="s3",
            uri=uri,
            params=params,
            cache=cache,
            retries=2,
            timeout=timeout,
            format=format,
        )

    @classmethod
    def glob(
        cls,
        pattern: str,
        *,
        root: str = ".",
        merge: str = "directory",
        format: str | None = None,
    ) -> Source:
        """Create a filesystem glob source."""
        return cls(
            kind="glob",
            uri=pattern,
            params={"root": root, "merge": merge},
            cache=False,
            retries=0,
            timeout=0.0,
            format=format,
        )

    @classmethod
    def api(
        cls,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: Any = None,
        jq: str | None = None,
        extract: str | None = None,
        format: str = "json",
        cache: bool = True,
        retries: int = 2,
        timeout: float = 30.0,
    ) -> Source:
        """Create a generic REST API source.

        ``extract`` is an alias for ``jq`` (JSONPath-like extraction path).
        If both are provided, ``jq`` takes precedence.
        """
        params: dict[str, Any] = {"method": method}
        if headers:
            params["headers"] = headers
        if body is not None:
            params["body"] = body
        if jq:
            params["jq"] = jq
        if extract:
            params["extract"] = extract
        return cls(
            kind="api",
            uri=url,
            params=params,
            cache=cache,
            retries=retries,
            timeout=timeout,
            format=format,
        )

    @classmethod
    def base64(
        cls,
        data: str,
        *,
        format: str = "bytes",
        cache: bool = True,
        retries: int = 0,
    ) -> Source:
        """Create a base64-encoded inline data source."""
        params: dict[str, Any] = {}
        if format and format != "bytes":
            params["format"] = format
        return cls(
            kind="base64",
            uri=data,
            params=params,
            cache=cache,
            retries=retries,
            timeout=0.0,
            format=format,
        )

    @classmethod
    def clipboard(cls, *, format: str = "text") -> Source:
        """Create a clipboard source (platform-dependent)."""
        return cls(
            kind="clipboard",
            uri="",
            params={},
            cache=False,
            retries=0,
            timeout=5.0,
            format=format,
        )

    # -- Serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (JSON-safe)."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Source:
        """Deserialize from a plain dict."""
        return cls(**d)


# ---------------------------------------------------------------------------
# Resolver protocol and registry
# ---------------------------------------------------------------------------

_SENTINEL = object()


class ResolverResult:
    """Result returned by a resolver: the fetched data plus metadata.

    Supports construction via either ``ResolverResult(data=..., metadata=...)``
    or ``ResolverResult(value=..., source_kind=...)`` for convenience.
    """

    __slots__ = ("_data", "_metadata")

    def __init__(
        self,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        *,
        value: Any = _SENTINEL,
        source_kind: str | None = None,
    ) -> None:
        # Support both (data=, metadata=) and (value=, source_kind=) patterns
        if value is not _SENTINEL:
            object.__setattr__(self, "_data", value)
        else:
            object.__setattr__(self, "_data", data)

        meta = dict(metadata) if metadata else {}
        if source_kind is not None:
            meta["source_kind"] = source_kind
        object.__setattr__(self, "_metadata", meta)

    @property
    def data(self) -> Any:
        """The resolved data."""
        return self._data

    @property
    def value(self) -> Any:
        """Alias for ``data``."""
        return self._data

    @property
    def metadata(self) -> dict[str, Any]:
        """Resolution metadata."""
        return self._metadata

    @property
    def source_kind(self) -> str | None:
        """Return the source kind from metadata, if present."""
        return self._metadata.get("source_kind")

    def __repr__(self) -> str:
        return f"ResolverResult(data={self._data!r}, metadata={self._metadata!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ResolverResult):
            return self._data == other._data and self._metadata == other._metadata
        return NotImplemented


@runtime_checkable
class SourceResolver(Protocol):
    """Protocol that all source resolvers must implement."""

    def can_handle(self, source: Source) -> bool:
        """Return True if this resolver can handle the given source kind."""
        ...

    def resolve(self, source: Source, secrets: dict[str, str] | None = ...) -> ResolverResult:
        """Fetch and return the data described by *source*."""
        ...


# Module-level resolver registry
_REGISTRY: list[SourceResolver] = []


def register_resolver(resolver: SourceResolver) -> None:
    """Add a resolver to the global registry."""
    _REGISTRY.append(resolver)
    logger.debug("Registered resolver: %s", type(resolver).__name__)


def get_resolver(source: Source) -> SourceResolver:
    """Return the first registered resolver that can handle *source*.

    Raises ``ValueError`` if no resolver matches.
    """
    for resolver in _REGISTRY:
        if resolver.can_handle(source):
            return resolver
    raise ValueError(
        f"No resolver registered for source kind={source.kind!r}, uri={source.uri!r}"
    )
