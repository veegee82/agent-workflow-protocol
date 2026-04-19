"""Thread-safety tests for observability writers.

These tests stress ``AuditTrail``, ``Tracer``, and ``MetricsCollector``
from many threads concurrently and assert that their invariants hold:

* ``AuditTrail.verify_chain`` stays True under parallel ``record()``
  calls (no lost or interleaved ``_seq``/``_prev_hash`` updates).
* ``Tracer`` never loses a completed span.
* ``MetricsCollector`` counters/histograms end up with the exact
  number of increments they received.
"""

from __future__ import annotations

import threading

from awp.runtime.observability import AuditTrail, MetricsCollector, Tracer


def test_audit_trail_hash_chain_under_concurrent_record(tmp_path):
    audit = AuditTrail(tmp_path, "stress-run")
    num_threads = 100
    per_thread = 100

    def worker(i: int) -> None:
        for j in range(per_thread):
            audit.record(
                event_type="stress",
                agent_id=f"t{i}",
                details={"i": i, "j": j},
            )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(audit._entries) == num_threads * per_thread
    # Sequence numbers must be contiguous 1..N with no duplicates.
    seqs = [e["seq"] for e in audit._entries]
    assert sorted(seqs) == list(range(1, num_threads * per_thread + 1))
    # The hash chain must verify.
    assert AuditTrail.verify_chain(audit._entries) is True


def test_audit_trail_flush_is_consistent_with_concurrent_writers(tmp_path):
    audit = AuditTrail(tmp_path, "flush-run")
    stop = threading.Event()

    def writer() -> None:
        i = 0
        while not stop.is_set():
            audit.record("e", "w", {"i": i})
            i += 1

    threads = [threading.Thread(target=writer) for _ in range(8)]
    for t in threads:
        t.start()
    for _ in range(5):
        audit.flush()
    stop.set()
    for t in threads:
        t.join()
    audit.flush()

    path = tmp_path / "flush-run.jsonl"
    assert path.exists()
    lines = [line for line in path.read_text().splitlines() if line]
    assert len(lines) > 0


def test_tracer_no_lost_spans_under_parallel_end(tmp_path):
    tracer = Tracer(tmp_path, "tracer-run")
    num_threads = 50
    per_thread = 40

    def worker() -> None:
        for _ in range(per_thread):
            sid = tracer.start_span("op")
            tracer.end_span(sid, status="ok")

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(tracer._completed) == num_threads * per_thread
    assert tracer._spans == {}


def test_metrics_collector_counter_exact_under_contention(tmp_path):
    metrics = MetricsCollector(tmp_path, "metrics-run")
    num_threads = 64
    per_thread = 250

    def worker() -> None:
        for _ in range(per_thread):
            metrics.increment("events", 1.0)
            metrics.histogram("latency", 0.5)

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert metrics._counters["events"] == float(num_threads * per_thread)
    assert len(metrics._histograms["latency"]) == num_threads * per_thread
