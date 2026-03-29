"""Resolver for clipboard sources (platform-dependent)."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from typing import Any

from awp.data.sources import ResolverResult, Source

logger = logging.getLogger(__name__)


def _read_clipboard() -> str:
    """Read text from the system clipboard using the first available tool.

    Tries tools in order: pbpaste (macOS), xclip, xsel (Linux),
    powershell (Windows). Uses whichever is found first.
    """
    # Try pbpaste (macOS, but may be available elsewhere)
    if shutil.which("pbpaste"):
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=5
        )
        return result.stdout

    # Try xclip (Linux)
    if shutil.which("xclip"):
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout

    # Try xsel (Linux)
    if shutil.which("xsel"):
        result = subprocess.run(
            ["xsel", "--clipboard", "--output"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout

    # Try powershell (Windows)
    if shutil.which("powershell"):
        result = subprocess.run(
            ["powershell", "-command", "Get-Clipboard"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout

    raise RuntimeError(
        f"No clipboard utility found on {platform.system()}. "
        "Install one of: pbpaste (macOS), xclip/xsel (Linux), powershell (Windows)."
    )


class ClipboardResolver:
    """Resolve ``kind='clipboard'`` sources from the system clipboard."""

    def can_handle(self, source: Source) -> bool:
        return source.kind == "clipboard"

    def resolve(self, source: Source, secrets: dict[str, str] | None = None) -> ResolverResult:
        logger.info("Reading from system clipboard")
        text = _read_clipboard()

        metadata: dict[str, Any] = {
            "source_kind": "clipboard",
            "length": len(text),
            "platform": platform.system(),
            "format": source.format or "text",
        }
        return ResolverResult(data=text, metadata=metadata)
