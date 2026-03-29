"""High-level input resolver with caching, retries, and parallel execution."""

from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import pickle
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from awp.data.sources import Source, get_resolver

logger = logging.getLogger(__name__)

# Exceptions that trigger retry with backoff
_RETRYABLE_EXCEPTIONS = (
    ConnectionError, TimeoutError, OSError, concurrent.futures.TimeoutError
)

# Try to include httpx transport errors if httpx is available
try:
    import httpx
    _RETRYABLE_EXCEPTIONS = (*_RETRYABLE_EXCEPTIONS, httpx.TransportError)  # type: ignore[assignment]
except ImportError:
    pass

# Backoff schedule (seconds)
_BACKOFF_DELAYS = (0.5, 1.0, 2.0)


def _substitute_secrets(obj: Any, secrets: dict[str, str]) -> Any:
    """Recursively replace ``$NAME`` patterns in all string values."""
    if isinstance(obj, str):
        return re.sub(
            r"\$([A-Z_][A-Z0-9_]*)",
            lambda m: secrets.get(m.group(1), m.group(0)),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _substitute_secrets(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_secrets(v, secrets) for v in obj]
    return obj


def _check_unresolved_secrets(obj: Any, secrets: dict[str, str]) -> None:
    """Raise ``ValueError`` if any ``$SECRET_NAME`` placeholders remain unresolved."""
    if isinstance(obj, str):
        for m in re.finditer(r"\$([A-Z_][A-Z0-9_]*)", obj):
            name = m.group(1)
            if name not in secrets:
                raise ValueError(
                    f"Unresolved secret placeholder ${name}. "
                    f"Provide it via secrets={{{name!r}: '...'}}"
                )
    elif isinstance(obj, dict):
        for v in obj.values():
            _check_unresolved_secrets(v, secrets)
    elif isinstance(obj, list):
        for v in obj:
            _check_unresolved_secrets(v, secrets)


def _cache_key(source: Source) -> str:
    """Compute a deterministic hash for a Source (for file-based caching)."""
    parts = f"{source.kind}:{source.uri}:{sorted(source.params.items())}"
    return hashlib.sha256(parts.encode()).hexdigest()[:32]


class InputResolver:
    """Resolve a dict of inputs, replacing ``Source`` values with fetched data.

    Features:
      - Parallel resolution via ``ThreadPoolExecutor``
      - File-based pickle cache (optional)
      - Exponential-backoff retry for transient errors
      - Recursive secret substitution in source params

    Usage::

        resolver = InputResolver(secrets={"API_KEY": "sk-..."})
        resolved = resolver.resolve_all({
            "data": Source.url("https://example.com/data.csv"),
            "config": {"threshold": 0.8},  # non-Source values pass through
        })
    """

    def __init__(
        self,
        secrets: dict[str, str] | None = None,
        max_workers: int = 4,
        cache_dir: Path | None = None,
    ) -> None:
        self._secrets = secrets or {}
        self._max_workers = max_workers
        self._cache_dir = cache_dir
        self._resolvers: dict[str, Any] = {}
        self._run_cache: dict[str, Any] = {}
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def register(self, kind: str, resolver: Any) -> None:
        """Register a resolver for a specific source kind.

        Registered resolvers take precedence over the global resolver registry.
        """
        self._resolvers[kind] = resolver

    def resolve_all(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Resolve all ``Source`` values in *inputs* and return a new dict.

        Non-``Source`` values are passed through unchanged.
        """
        # Ensure built-in resolvers are registered
        import awp.data.resolvers  # noqa: F401

        source_keys: list[str] = []
        other: dict[str, Any] = {}

        for key, value in inputs.items():
            if isinstance(value, Source):
                source_keys.append(key)
            else:
                other[key] = value

        if not source_keys:
            return dict(inputs)

        result = dict(other)
        metadata_map: dict[str, dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._resolve_one, key, inputs[key]): key
                for key in source_keys
            }
            for future in as_completed(futures):
                key = futures[future]
                resolved_key, data, meta = future.result()
                result[resolved_key] = data
                if meta:
                    metadata_map[resolved_key] = meta

        if metadata_map:
            logger.info(
                "Resolved %d source(s): %s",
                len(metadata_map),
                ", ".join(metadata_map.keys()),
            )

        return result

    def _get_resolver(self, source: Source) -> Any:
        """Return the resolver for *source*, checking instance registry first."""
        if source.kind in self._resolvers:
            return self._resolvers[source.kind]
        return get_resolver(source)

    def _call_resolver(self, resolver: Any, source: Source) -> Any:
        """Call resolver.resolve(), handling both 1-arg and 2-arg signatures."""
        import inspect

        sig = inspect.signature(resolver.resolve)
        params = list(sig.parameters.keys())
        # If resolver accepts 2+ params (source + secrets), pass secrets
        if len(params) >= 2:
            return resolver.resolve(source, self._secrets)
        return resolver.resolve(source)

    def _resolve_one(
        self, key: str, value: Any
    ) -> tuple[str, Any, dict[str, Any] | None]:
        """Resolve a single Source with caching and retries."""
        if not isinstance(value, Source):
            return key, value, None

        source = value

        # Substitute secrets in params
        if source.params:
            new_params = _substitute_secrets(source.params, self._secrets)
            # Validate all secrets were resolved (no remaining $PLACEHOLDERS)
            if self._secrets is not None:
                _check_unresolved_secrets(new_params, self._secrets)
            source = Source(
                kind=source.kind,
                uri=source.uri,
                params=new_params,
                cache=source.cache,
                retries=source.retries,
                timeout=source.timeout,
                format=source.format,
            )

        # Check per-run in-memory cache
        ck = _cache_key(source)
        if source.cache and ck in self._run_cache:
            logger.debug("Run-cache hit for '%s'", key)
            cached = self._run_cache[ck]
            return key, cached["data"], cached.get("metadata")

        # Check file-based cache
        if source.cache and self._cache_dir:
            cache_path = self._cache_dir / f"{ck}.pkl"
            if cache_path.exists():
                logger.debug("File-cache hit for '%s' (%s)", key, ck)
                try:
                    with open(cache_path, "rb") as f:
                        cached = pickle.load(f)
                    self._run_cache[ck] = cached
                    return key, cached["data"], cached["metadata"]
                except Exception:
                    logger.warning("Failed to load cache for '%s'; re-resolving", key)

        # Resolve with retries
        resolver = self._get_resolver(source)
        last_exc: Exception | None = None
        max_attempts = source.retries + 1

        for attempt in range(max_attempts):
            try:
                # Enforce timeout if set
                if source.timeout and source.timeout > 0:
                    from concurrent.futures import ThreadPoolExecutor as _TP
                    with _TP(max_workers=1) as tp:
                        fut = tp.submit(self._call_resolver, resolver, source)
                        result = fut.result(timeout=source.timeout)
                else:
                    result = self._call_resolver(resolver, source)

                data = result.data if hasattr(result, "data") else result.value
                metadata = result.metadata if hasattr(result, "metadata") else {}

                # Write to per-run cache
                if source.cache:
                    self._run_cache[ck] = {"data": data, "metadata": metadata}

                # Write to file-based cache
                if source.cache and self._cache_dir:
                    cache_path = self._cache_dir / f"{ck}.pkl"
                    try:
                        with open(cache_path, "wb") as f:
                            pickle.dump({"data": data, "metadata": metadata}, f)
                        logger.debug("Cached '%s' -> %s", key, cache_path)
                    except Exception as exc:
                        logger.warning("Failed to cache '%s': %s", key, exc)

                return key, data, metadata

            except _RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt < source.retries:
                    delay = _BACKOFF_DELAYS[min(attempt, len(_BACKOFF_DELAYS) - 1)]
                    logger.warning(
                        "Retryable error resolving '%s' (attempt %d/%d): %s. "
                        "Retrying in %.1fs...",
                        key,
                        attempt + 1,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Failed to resolve '%s' after %d attempts: %s",
                        key,
                        max_attempts,
                        exc,
                    )
                    raise

        # Should not reach here, but satisfy type checker
        raise last_exc  # type: ignore[misc]
