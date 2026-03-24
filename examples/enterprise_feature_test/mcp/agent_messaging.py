"""
Built-in MCP Tools: agent.send_message, agent.list_messages

File-based message queue for inter-agent communication.
Auto-generated for tool implementation mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class FastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn
        return _decorator


app = FastMCP("agent")

_MESSAGES_DIR = Path(".messages")


def _ensure_dirs():
    _MESSAGES_DIR.mkdir(exist_ok=True)


@app.tool("agent.send_message")
def send_message(
    *,
    to: str,
    content: Any,
    channel: str = "direct",
    type: str = "event",
    _secrets: dict = {},
) -> Dict[str, Any]:
    """Send a message to another agent via the message bus.

    Args:
        to: Target agent ID or '*' for broadcast.
        content: Message content (any JSON-serializable value).
        channel: Channel name (e.g., 'direct', 'alerts', 'metrics').
        type: Message type ('request', 'response', 'event').
    """
    try:
        _ensure_dirs()
        now = datetime.now(timezone.utc)

        message = {
            "id": f"msg_{now.strftime('%Y%m%d%H%M%S%f')}",
            "from": "current_agent",  # Replaced by runtime with actual agent ID
            "to": to,
            "channel": channel,
            "type": type,
            "content": content,
            "timestamp": now.isoformat(),
        }

        # Write to recipient's inbox (or broadcast directory)
        if to == "*":
            inbox = _MESSAGES_DIR / "_broadcast"
        else:
            inbox = _MESSAGES_DIR / to

        inbox.mkdir(exist_ok=True)
        msg_file = inbox / f"{message['id']}.json"
        msg_file.write_text(json.dumps(message, indent=2, default=str), encoding="utf-8")

        return {
            "ok": True,
            "status": 200,
            "data": {
                "message_id": message["id"],
                "to": to,
                "channel": channel,
                "timestamp": now.isoformat(),
            },
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}


@app.tool("agent.list_messages")
def list_messages(
    *,
    from_agent: str = None,
    channel: str = None,
    limit: int = 50,
    _secrets: dict = {},
) -> Dict[str, Any]:
    """List messages received from other agents.

    Args:
        from_agent: Filter by sender agent ID.
        channel: Filter by channel name.
        limit: Maximum messages to return.
    """
    try:
        _ensure_dirs()
        messages = []

        # Check own inbox and broadcast
        for inbox_name in [_MESSAGES_DIR / "current_agent", _MESSAGES_DIR / "_broadcast"]:
            if inbox_name.exists():
                for msg_file in sorted(inbox_name.glob("*.json")):
                    msg = json.loads(msg_file.read_text(encoding="utf-8"))

                    if from_agent and msg.get("from") != from_agent:
                        continue
                    if channel and msg.get("channel") != channel:
                        continue

                    messages.append(msg)

        messages.sort(key=lambda m: m.get("timestamp", ""), reverse=True)

        return {
            "ok": True,
            "status": 200,
            "data": {
                "messages": messages[:limit],
                "total": len(messages),
                "filters": {"from_agent": from_agent, "channel": channel},
            },
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "status": 500, "data": {}, "error": str(e)}
