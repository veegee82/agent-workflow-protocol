"""Tests for the observability module (Tracer, MetricsCollector, AuditTrail)."""

import json
import time
from pathlib import Path

from awp.runtime.observability import (
    Tracer,
    MetricsCollector,
    AuditTrail,
    ObservabilityContext,
)


class TestTracer:
    def test_start_and_end_span(self, tmp_path):
        tracer = Tracer(tmp_path, "test-run")
        span_id = tracer.start_span("workflow.run")
        assert isinstance(span_id, str)
        assert len(span_id) == 16

        time.sleep(0.01)
        tracer.end_span(span_id, status="ok")
        path = tracer.flush()

        assert path is not None
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1

        span = json.loads(lines[0])
        assert span["name"] == "workflow.run"
        assert span["status"] == "ok"
        assert span["duration_ms"] >= 0

    def test_parent_child_spans(self, tmp_path):
        tracer = Tracer(tmp_path, "test-run")
        root = tracer.start_span("workflow")
        child = tracer.start_span("agent.data_collector", parent_id=root)

        tracer.end_span(child, status="ok")
        tracer.end_span(root, status="ok")
        path = tracer.flush()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

        child_span = json.loads(lines[0])
        root_span = json.loads(lines[1])
        assert child_span["parent_id"] == root_span["span_id"]

    def test_span_attributes(self, tmp_path):
        tracer = Tracer(tmp_path, "test-run")
        span_id = tracer.start_span("test", attributes={"agent": "a1"})
        tracer.end_span(span_id, attributes={"result": "ok"})
        path = tracer.flush()

        span = json.loads(path.read_text().strip())
        assert span["attributes"]["agent"] == "a1"
        assert span["attributes"]["result"] == "ok"

    def test_flush_empty(self, tmp_path):
        tracer = Tracer(tmp_path, "test-run")
        assert tracer.flush() is None


class TestMetricsCollector:
    def test_counter_increment(self, tmp_path):
        metrics = MetricsCollector(tmp_path, "test-run")
        metrics.increment("agent.executions", labels={"agent": "a1"})
        metrics.increment("agent.executions", labels={"agent": "a1"})
        metrics.increment("agent.executions", labels={"agent": "a2"})
        path = metrics.flush()

        data = json.loads(path.read_text())
        assert data["counters"]["agent.executions{agent=a1}"] == 2.0
        assert data["counters"]["agent.executions{agent=a2}"] == 1.0

    def test_histogram(self, tmp_path):
        metrics = MetricsCollector(tmp_path, "test-run")
        metrics.histogram("agent.duration_s", 1.5, labels={"agent": "a1"})
        metrics.histogram("agent.duration_s", 2.5, labels={"agent": "a1"})
        path = metrics.flush()

        data = json.loads(path.read_text())
        hist = data["histograms"]["agent.duration_s{agent=a1}"]
        assert hist["count"] == 2
        assert hist["sum"] == 4.0
        assert hist["min"] == 1.5
        assert hist["max"] == 2.5

    def test_flush_empty(self, tmp_path):
        metrics = MetricsCollector(tmp_path, "test-run")
        assert metrics.flush() is None


class TestAuditTrail:
    def test_record_creates_hash_chain(self, tmp_path):
        audit = AuditTrail(tmp_path, "test-run")
        audit.record("workflow.start", details={"task": "test"})
        audit.record("agent.start", agent_id="a1")
        audit.record("agent.complete", agent_id="a1")
        path = audit.flush()

        lines = path.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines]
        assert len(entries) == 3

        # Verify chain
        assert entries[0]["prev_hash"] == "0" * 64
        assert entries[1]["prev_hash"] == entries[0]["hash"]
        assert entries[2]["prev_hash"] == entries[1]["hash"]

    def test_verify_chain(self, tmp_path):
        audit = AuditTrail(tmp_path, "test-run")
        audit.record("event1")
        audit.record("event2")
        audit.record("event3")
        path = audit.flush()

        lines = path.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines]
        assert AuditTrail.verify_chain(entries) is True

    def test_tampered_chain_detected(self, tmp_path):
        audit = AuditTrail(tmp_path, "test-run")
        audit.record("event1")
        audit.record("event2")
        path = audit.flush()

        lines = path.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines]

        # Tamper with first entry
        entries[0]["details"] = {"tampered": True}
        assert AuditTrail.verify_chain(entries) is False

    def test_sequential_numbering(self, tmp_path):
        audit = AuditTrail(tmp_path, "test-run")
        e1 = audit.record("a")
        e2 = audit.record("b")
        assert e1["seq"] == 1
        assert e2["seq"] == 2


class TestObservabilityContext:
    def test_from_config_all_disabled(self):
        class MockManifest:
            observability = None

        ctx = ObservabilityContext.from_config(MockManifest(), Path("/tmp"), "run1")
        assert ctx.tracer is None
        assert ctx.metrics is None
        assert ctx.audit is None

    def test_flush_all_no_error(self):
        ctx = ObservabilityContext()
        ctx.flush_all()  # Should not raise
