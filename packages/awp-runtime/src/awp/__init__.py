"""AWP — Agent Workflow Protocol runtime library.

Provides execution engines, LLM clients, data API, and tools for running AWP workflows.
"""

def _get_version() -> str:
    """Read version from installed package metadata, fallback to default."""
    try:
        from importlib.metadata import version
        return version("awp-agents")
    except Exception:
        try:
            from importlib.metadata import version
            return version("awp-runtime")
        except Exception:
            return "0.0.0"

__version__ = _get_version()

__all__ = ["__version__"]
