"""Allow running AWP as: python -m awp

This is the cross-platform fallback when the ``awp`` console script
is not on PATH (common on Windows after ``pip install --user``).

Usage::

    python -m awp studio
    python -m awp validate path/to/workflow
    python -m awp run path/to/workflow --task "..."
"""

from awp.cli import _main

_main()
