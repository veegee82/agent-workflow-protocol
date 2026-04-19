"""v0 default for the ``pattern_library`` artifact.

The pattern library index itself is rendered dynamically at prompt-build
time from ``awp.patterns``; the registry cannot snapshot the registry
content and keep it current. What the registry DOES own is the short
framing header that introduces the dynamically rendered section inside
the manager system prompt.
"""

from __future__ import annotations

CONTENT = "#### Pattern + Archetype Library"
