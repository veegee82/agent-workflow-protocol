"""AWP — Agent Workflow Protocol core library.

Provides models, parser, validator, and tools for the AWP specification.
For the execution runtime, install ``awp-runtime``.
"""

def _get_version() -> str:
    """Read version from installed package metadata, fallback to default."""
    try:
        from importlib.metadata import version
        return version("awp-agents")
    except Exception:
        try:
            from importlib.metadata import version
            return version("awp-core")
        except Exception:
            return "0.0.0"

__version__ = _get_version()

from .agent import AWPAgent

__all__ = ["AWPAgent", "__version__"]
