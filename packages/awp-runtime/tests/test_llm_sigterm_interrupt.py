"""Regression test for Defect 1 — SIGTERM watchdog aborts blocking httpx calls.

Scenario reproduced in Session 4d: the main thread was blocked inside
``httpx.Client.post()`` when SIGTERM arrived. The Python-level signal
handler set ``signal_state["pending"] = "sigterm"`` but the blocking C
call never observed it, so the delegation loop's ``finally`` never ran,
no ``run.complete`` was emitted, and the DB row stayed ``running`` until
the experiment watchdog SIGKILLed the process.

The fix registers every live ``LLMClient`` in a module-level WeakSet so
that a watchdog thread (installed inside ``_signal_handler``) can close
every client from a different thread, which aborts the in-flight
transport and raises ``httpx.CloseError`` / ``httpx.ReadError`` into the
blocking call. The blocking call's caller then falls through its
``finally``, emits the terminal event, and exits cleanly.
"""

from __future__ import annotations

import threading
import time

from awp.runtime.llm import _LIVE_CLIENTS, LLMClient


def test_close_all_aborts_registered_clients(monkeypatch):
    """LLMClient.close_all() must close every live instance."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-dummy")
    c1 = LLMClient(model="openai/gpt-5-mini")
    c2 = LLMClient(model="openai/gpt-5-mini")

    assert c1 in _LIVE_CLIENTS
    assert c2 in _LIVE_CLIENTS
    assert not c1._closed
    assert not c2._closed

    closed = LLMClient.close_all()

    assert closed >= 2
    assert c1._closed
    assert c2._closed


def test_close_is_idempotent(monkeypatch):
    """Calling close() twice must not raise."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-dummy")
    c = LLMClient(model="openai/gpt-5-mini")
    c.close()
    c.close()  # second call must be a no-op
    assert c._closed


def test_signal_watchdog_aborts_blocking_post(monkeypatch):
    """Simulate the Session 4d failure: thread-1 blocks in httpx.post
    against a slow server, thread-2 fires close_all() to simulate the
    SIGTERM watchdog. The blocking post must raise promptly so the
    caller can reach its ``finally`` block.
    """
    import http.server
    import socketserver
    import threading as _th

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-dummy")

    # Start a local HTTP server that accepts the connection but never
    # writes a response body — simulates a slow LLM provider. The client
    # then blocks in a socket read that only breaks when the transport
    # is closed from another thread.
    class _SlowHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            # Read the request but never send a response.
            length = int(self.headers.get("Content-Length", "0"))
            try:
                self.rfile.read(length)
            except Exception:
                return
            # Sleep long enough that the test's close_all() fires first.
            time.sleep(30)

        def log_message(self, *a, **kw):
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), _SlowHandler)
    port = server.server_address[1]
    server_thread = _th.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        client = LLMClient(
            model="openai/gpt-5-mini",
            base_url=f"http://127.0.0.1:{port}",
            timeout=60,
        )

        outcome: dict[str, object] = {}

        def _blocker() -> None:
            try:
                client._client.post(
                    f"http://127.0.0.1:{port}/chat/completions",
                    json={"model": "x", "messages": []},
                )
                outcome["raised"] = False
            except Exception as exc:  # noqa: BLE001
                outcome["raised"] = True
                outcome["exc_type"] = type(exc).__name__

        t = threading.Thread(target=_blocker, daemon=True)
        t.start()

        # Give the blocker time to connect + send the request and enter
        # the socket-read for the response.
        time.sleep(1.0)

        # Simulate the SIGTERM watchdog: close all live clients from
        # this (other) thread. This must unblock the httpx.post().
        LLMClient.close_all()

        t.join(timeout=5.0)
        assert not t.is_alive(), (
            "blocker thread must exit after close_all() — the signal "
            "watchdog would otherwise be ineffective"
        )
        assert outcome.get("raised") is True, (
            "blocking httpx.post must raise after the client was closed "
            f"from another thread — got {outcome!r}"
        )
    finally:
        server.shutdown()
        server.server_close()
