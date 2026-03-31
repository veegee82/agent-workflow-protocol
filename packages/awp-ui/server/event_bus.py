"""Internal async event bus for streaming run events to WebSocket clients."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import AsyncGenerator

from server.models import RunEvent

logger = logging.getLogger(__name__)


class EventBus:
    """Fan-out event bus: multiple async subscribers per run_id.

    Thread-safe: ``emit`` can be called from any thread via
    ``call_soon_threadsafe`` on the event loop.

    Events are buffered per run so that late-connecting WebSocket clients
    receive all events that were emitted before they subscribed.
    """

    def __init__(self) -> None:
        # run_id -> list of asyncio.Queue (one per subscriber)
        self._subscribers: dict[str, list[asyncio.Queue[RunEvent | None]]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        # Buffer of past events per run (replayed to late subscribers)
        self._buffers: dict[str, list[RunEvent]] = defaultdict(list)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind to the running asyncio event loop (called at startup)."""
        self._loop = loop

    async def emit(self, run_id: str, event: RunEvent) -> None:
        """Push an event to all subscribers for the given run_id and persist to DB."""
        async with self._lock:
            # Buffer for late subscribers
            self._buffers[run_id].append(event)
            queues = self._subscribers.get(run_id, [])
            for q in queues:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Subscriber queue full for run %s, dropping event", run_id
                    )

        # Persist event to database (best-effort, non-blocking)
        try:
            from server.app import store
            await store.save_event(
                run_id=run_id,
                seq=event.seq,
                event_type=event.type.value if hasattr(event.type, 'value') else str(event.type),
                data=event.data,
                timestamp=event.timestamp.isoformat() if hasattr(event.timestamp, 'isoformat') else str(event.timestamp),
            )
        except Exception:
            logger.debug("Failed to persist event for run %s", run_id, exc_info=True)

    def emit_threadsafe(self, run_id: str, event: RunEvent) -> None:
        """Emit from a synchronous / background thread.

        Schedules the coroutine on the bound event loop.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.warning("No event loop bound; cannot emit event for run %s", run_id)
            return
        asyncio.run_coroutine_threadsafe(self.emit(run_id, event), loop)

    async def subscribe(self, run_id: str) -> AsyncGenerator[RunEvent, None]:
        """Yield events for the given run_id until the run completes.

        Replays any buffered events first, then streams live events.
        Callers should iterate with ``async for event in bus.subscribe(rid):``.
        A ``None`` sentinel terminates the generator.
        """
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(maxsize=1024)
        async with self._lock:
            # Replay buffered events
            for past_event in self._buffers.get(run_id, []):
                try:
                    queue.put_nowait(past_event)
                except asyncio.QueueFull:
                    break
            self._subscribers[run_id].append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            async with self._lock:
                subs = self._subscribers.get(run_id, [])
                if queue in subs:
                    subs.remove(queue)
                if not subs:
                    self._subscribers.pop(run_id, None)

    async def close_run(self, run_id: str) -> None:
        """Send sentinel to all subscribers of a run, signalling completion."""
        async with self._lock:
            queues = self._subscribers.get(run_id, [])
            for q in queues:
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            # Clean up buffer after a short delay to allow late subscribers
            self._buffers.pop(run_id, None)

    def close_run_threadsafe(self, run_id: str) -> None:
        """Close a run from a background thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.close_run(run_id), loop)


# Module-level singleton
event_bus = EventBus()
