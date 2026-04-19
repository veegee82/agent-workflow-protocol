"""v0 default for the ``tool_description_templates`` artifact.

This is the framing header shown to the manager when dynamic / induced
tools from prior runs are listed. The tool entries themselves are
rendered dynamically from the tool registry at prompt-build time; the
artifact only owns the introductory boilerplate paragraph.
"""

from __future__ import annotations

CONTENT = (
    "These tools are already registered and can be added to any worker's "
    '`tools_allowed` list. Use `"dynamic.*"` to give a worker ALL dynamic tools, '
    'or list specific ones like `"dynamic.my_tool"`.\n'
)
