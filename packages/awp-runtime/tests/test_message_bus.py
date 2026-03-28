"""Tests for the in-memory message bus."""

from awp.runtime.message_bus import MessageBus


class TestMessageBus:
    def test_send_and_receive(self):
        bus = MessageBus()
        msg_id = bus.send("agent_a", "agent_b", {"data": "hello"})
        assert msg_id

        messages = bus.list_messages("agent_b")
        assert len(messages) == 1
        assert messages[0]["content"] == {"data": "hello"}
        assert messages[0]["from"] == "agent_a"

    def test_sender_does_not_see_own_direct(self):
        bus = MessageBus()
        bus.send("agent_a", "agent_b", "test")
        messages = bus.list_messages("agent_a")
        assert len(messages) == 0

    def test_broadcast(self):
        bus = MessageBus()
        bus.broadcast("agent_a", {"alert": "high"}, channel="alerts")

        # agent_b sees it
        msgs_b = bus.list_messages("agent_b")
        assert len(msgs_b) == 1
        assert msgs_b[0]["channel"] == "alerts"

        # agent_a (sender) does not see own broadcast
        msgs_a = bus.list_messages("agent_a")
        assert len(msgs_a) == 0

    def test_channel_filter(self):
        bus = MessageBus()
        bus.send("a", "b", "msg1", channel="direct")
        bus.send("a", "b", "msg2", channel="metrics")

        direct_msgs = bus.list_messages("b", channel="direct")
        assert len(direct_msgs) == 1
        assert direct_msgs[0]["content"] == "msg1"

        metrics_msgs = bus.list_messages("b", channel="metrics")
        assert len(metrics_msgs) == 1
        assert metrics_msgs[0]["content"] == "msg2"

    def test_from_agent_filter(self):
        bus = MessageBus()
        bus.send("agent_a", "agent_c", "from_a")
        bus.send("agent_b", "agent_c", "from_b")

        msgs = bus.list_messages("agent_c", from_agent="agent_a")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "from_a"

    def test_message_ordering_fifo(self):
        bus = MessageBus()
        bus.send("a", "b", "first")
        bus.send("a", "b", "second")
        bus.send("a", "b", "third")

        msgs = bus.list_messages("b")
        # Newest first (reversed)
        assert msgs[0]["content"] == "third"
        assert msgs[2]["content"] == "first"

    def test_limit(self):
        bus = MessageBus()
        for i in range(10):
            bus.send("a", "b", f"msg{i}")

        msgs = bus.list_messages("b", limit=3)
        assert len(msgs) == 3

    def test_get_channel_messages(self):
        bus = MessageBus()
        bus.send("a", "b", "msg1", channel="test")
        bus.send("c", "d", "msg2", channel="test")

        channel_msgs = bus.get_channel_messages("test")
        assert len(channel_msgs) == 2

    def test_clear(self):
        bus = MessageBus()
        bus.send("a", "b", "test")
        bus.broadcast("a", "alert")
        bus.clear()

        assert bus.list_messages("b") == []
        assert bus.get_channel_messages("direct") == []

    def test_message_envelope_fields(self):
        bus = MessageBus()
        bus.send(
            "agent_a",
            "agent_b",
            {"key": "value"},
            channel="metrics",
            msg_type="request",
        )

        msgs = bus.list_messages("agent_b")
        msg = msgs[0]
        assert "id" in msg
        assert "timestamp" in msg
        assert msg["from"] == "agent_a"
        assert msg["to"] == "agent_b"
        assert msg["channel"] == "metrics"
        assert msg["type"] == "request"
