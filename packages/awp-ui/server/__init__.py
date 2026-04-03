"""AWP UI Server — FastAPI backend with WebSocket streaming for AWP runtime."""

def _get_version() -> str:
    """Read version from installed package metadata, fallback to default."""
    try:
        from importlib.metadata import version
        return version("awp-agents")
    except Exception:
        try:
            from importlib.metadata import version
            return version("awp-ui")
        except Exception:
            return "0.0.0"

__version__ = _get_version()
