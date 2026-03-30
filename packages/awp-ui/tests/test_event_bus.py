"""Tests for the async event bus."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from server.event_bus import EventBus
from server.models import EventType, RunEvent


def _make_event(run_id: str, seq: int = 1, event_type: EventType = EventType.LOG) -> RunEvent:
    return RunEvent(
        run_id=run_id,
        seq=seq,
        type=event_type,
        data={"message": f"Event {seq}"},
        timestamp=datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_subscribe_and_emit() -> None:
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())

    received: list[RunEvent] = []

    async def collector():
        async for event in bus.subscribe("run1"):
            received.append(event)

    task = asyncio.create_task(collector())

    # Give subscriber time to register
    await asyncio.sleep(0.05)

    await bus.emit("run1", _make_event("run1", 1))
    await bus.emit("run1", _make_event("run1", 2))
    await bus.close_run("run1")

    await asyncio.wait_for(task, timeout=2.0)

    assert len(received) == 2
    assert received[0].seq == 1
    assert received[1].seq == 2


@pytest.mark.asyncio
async def test_multiple_subscribers() -> None:
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())

    received_a: list[RunEvent] = []
    received_b: list[RunEvent] = []

    async def collector_a():
        async for event in bus.subscribe("run1"):
            received_a.append(event)

    async def collector_b():
        async for event in bus.subscribe("run1"):
            received_b.append(event)

    task_a = asyncio.create_task(collector_a())
    task_b = asyncio.create_task(collector_b())
    await asyncio.sleep(0.05)

    await bus.emit("run1", _make_event("run1", 1))
    await bus.close_run("run1")

    await asyncio.wait_for(task_a, timeout=2.0)
    await asyncio.wait_for(task_b, timeout=2.0)

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_separate_run_ids() -> None:
    """Events for different run_ids should not cross-pollinate."""
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())

    received_1: list[RunEvent] = []
    received_2: list[RunEvent] = []

    async def collector_1():
        async for event in bus.subscribe("run1"):
            received_1.append(event)

    async def collector_2():
        async for event in bus.subscribe("run2"):
            received_2.append(event)

    t1 = asyncio.create_task(collector_1())
    t2 = asyncio.create_task(collector_2())
    await asyncio.sleep(0.05)

    await bus.emit("run1", _make_event("run1", 1))
    await bus.emit("run2", _make_event("run2", 1))
    await bus.emit("run2", _make_event("run2", 2))
    await bus.close_run("run1")
    await bus.close_run("run2")

    await asyncio.wait_for(t1, timeout=2.0)
    await asyncio.wait_for(t2, timeout=2.0)

    assert len(received_1) == 1
    assert len(received_2) == 2


@pytest.mark.asyncio
async def test_emit_threadsafe() -> None:
    """Test that emit_threadsafe works from the same thread (degenerate case)."""
    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus.bind_loop(loop)

    received: list[RunEvent] = []

    async def collector():
        async for event in bus.subscribe("run1"):
            received.append(event)

    task = asyncio.create_task(collector())
    await asyncio.sleep(0.05)

    # emit_threadsafe schedules on the loop
    bus.emit_threadsafe("run1", _make_event("run1", 1))

    # Give scheduled coroutine time to execute
    await asyncio.sleep(0.1)

    bus.close_run_threadsafe("run1")
    await asyncio.sleep(0.1)

    await asyncio.wait_for(task, timeout=2.0)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_close_run_terminates_subscriber() -> None:
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())

    finished = False

    async def collector():
        nonlocal finished
        async for _ in bus.subscribe("run1"):
            pass
        finished = True

    task = asyncio.create_task(collector())
    await asyncio.sleep(0.05)

    await bus.close_run("run1")
    await asyncio.wait_for(task, timeout=2.0)
    assert finished is True


@pytest.mark.asyncio
async def test_emit_without_subscribers() -> None:
    """Emitting to a run with no subscribers should not raise."""
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    await bus.emit("no_subscribers", _make_event("no_subscribers", 1))
    # No error means success


@pytest.mark.asyncio
async def test_emit_threadsafe_no_loop() -> None:
    """emit_threadsafe with no bound loop should not raise."""
    bus = EventBus()
    # No bind_loop call
    bus.emit_threadsafe("run1", _make_event("run1", 1))
    # No error means success


@pytest.mark.asyncio
async def test_subscriber_cleanup() -> None:
    """After a subscriber finishes, it should be removed from the internal list."""
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())

    async def collector():
        async for _ in bus.subscribe("run1"):
            pass

    task = asyncio.create_task(collector())
    await asyncio.sleep(0.05)

    await bus.close_run("run1")
    await asyncio.wait_for(task, timeout=2.0)

    # Internal subscribers dict should be cleaned up
    assert "run1" not in bus._subscribers
