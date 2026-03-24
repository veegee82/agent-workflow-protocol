"""AWP Message Bus -- In-memory inter-agent communication.

Simple dict-of-lists implementation supporting direct, broadcast,
and channel-based messaging.  Production deployments can swap in
Redis, NATS, Kafka, or RabbitMQ backends.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MessageBus:
    """In-memory message bus for inter-agent communication."""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        # Per-agent inboxes: agent_id → list of messages
        self._inboxes: dict[str, list[dict[str, Any]]] = {}
        # Per-channel message log: channel_name → list of messages
        self._channels: dict[str, list[dict[str, Any]]] = {}
        # Broadcast messages (visible to all)
        self._broadcasts: list[dict[str, Any]] = []

    def send(
        self,
        from_agent: str,
        to_agent: str,
        content: Any,
        channel: str = "direct",
        msg_type: str = "event",
    ) -> str:
        """Send a message from one agent to another.

        Args:
            from_agent: Sender agent ID.
            to_agent: Recipient agent ID or ``"*"`` for broadcast.
            content: Message payload (any JSON-serializable value).
            channel: Channel name (default ``"direct"``).
            msg_type: Message type (``"request"``/``"response"``/``"event"``).

        Returns:
            The message ID (UUID).
        """
        msg_id = str(uuid.uuid4())
        envelope = {
            "id": msg_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from": from_agent,
            "to": to_agent,
            "channel": channel,
            "type": msg_type,
            "content": content,
        }

        if to_agent == "*":
            # Broadcast
            self._broadcasts.append(envelope)
            self._channels.setdefault(channel, []).append(envelope)
            logger.info("Bus: broadcast from %s on channel '%s'", from_agent, channel)
        else:
            # Direct
            self._inboxes.setdefault(to_agent, []).append(envelope)
            self._channels.setdefault(channel, []).append(envelope)
            logger.info("Bus: %s → %s on channel '%s'", from_agent, to_agent, channel)

        return msg_id

    def broadcast(
        self,
        from_agent: str,
        content: Any,
        channel: str = "alerts",
    ) -> str:
        """Broadcast a message to all agents."""
        return self.send(from_agent, "*", content, channel=channel, msg_type="event")

    def list_messages(
        self,
        agent_id: str,
        channel: Optional[str] = None,
        from_agent: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List messages for an agent (direct + broadcasts).

        Args:
            agent_id: The recipient agent ID.
            channel: Optional channel filter.
            from_agent: Optional sender filter.
            limit: Maximum number of messages to return.

        Returns:
            List of message envelopes, newest first.
        """
        messages: list[dict[str, Any]] = []

        # Direct messages
        for msg in self._inboxes.get(agent_id, []):
            messages.append(msg)

        # Broadcasts (exclude own messages)
        for msg in self._broadcasts:
            if msg["from"] != agent_id:
                messages.append(msg)

        # Apply filters
        if channel:
            messages = [m for m in messages if m.get("channel") == channel]
        if from_agent:
            messages = [m for m in messages if m.get("from") == from_agent]

        # Sort by timestamp descending, limit
        messages.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        return messages[:limit]

    def get_channel_messages(self, channel: str) -> list[dict[str, Any]]:
        """Get all messages on a specific channel."""
        return list(self._channels.get(channel, []))

    def clear(self) -> None:
        """Clear all messages (for testing)."""
        self._inboxes.clear()
        self._channels.clear()
        self._broadcasts.clear()
