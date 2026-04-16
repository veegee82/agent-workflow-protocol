"""Regression test for Defect 2 — ``code.execute`` 'I/O operation on closed file.'

Observed in experiment ``adversarial-artifact-consistency-20260415-081746-d93ee2``:
after the first successful ``code.execute`` call in a worker, the next
call returned in ~6 ms with ``error='I/O operation on closed file.'``
The persistent executor reuses the subprocess across calls, so any
module-level monkey-patch installed by the ``_code_execute`` preamble
persists. The preamble captured ``_orig_open = _builtins.open`` and
wrapped it in ``_safe_open``; on the next call ``_builtins.open`` was
already ``_safe_open``, so the new preamble rebuilt a chain of wrappers
whose deepest file handle was closed on first ``__exit__``. Subsequent
writes through the stale proxy raised ``ValueError('I/O operation on
closed file.')`` from inside the file-validator / ``_AWPFileProxy``.

The fix stashes the real ``open`` on a sentinel
``_builtins._awp_real_open`` attribute the first time the preamble runs,
and always binds ``_orig_open`` to that value. We also guard
``_builtins.open = _safe_open`` with a ``_awp_wrapped`` marker so the
wrapper is installed exactly once per subprocess.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from awp.runtime.executor_factory import create_executor
from awp.runtime.tools import ToolRegistry


@pytest.fixture
def tool_registry():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="awp_io_closed_"))
    reg = ToolRegistry(workflow_dir=tmp)
    ex = create_executor(None, working_dir=tmp / "workspace")
    reg.set_code_executor(ex)
    try:
        yield reg, tmp
    finally:
        try:
            ex.cleanup()
        except Exception:
            pass


def test_repeated_code_execute_does_not_leak_closed_file(tool_registry):
    """Calling ``code.execute`` many times in a row must not surface
    'I/O operation on closed file.' — the preamble must be idempotent
    across the persistent-executor's reused subprocess.
    """
    reg, tmp = tool_registry
    target = tmp / "out.html"

    code = f"""
with open({str(target)!r}, 'w', encoding='utf-8') as f:
    f.write('<html><body>hi</body></html>')
print('wrote')
"""

    # Run the same code five times back-to-back — enough to accumulate
    # multiple layers of wrapper chains under the old bug.
    for i in range(5):
        result = reg.call("code.execute", {"code": code})
        assert result.get("ok"), (
            f"iteration {i}: code.execute failed — "
            f"error={result.get('error')!r}"
        )
        err = result.get("error") or ""
        assert "closed file" not in err.lower(), (
            f"iteration {i}: regression — got closed-file error: {err!r}"
        )


def test_preamble_idempotent_builtins_wrapping(tool_registry):
    """After repeated runs, ``_builtins.open`` must still be exactly one
    ``_safe_open`` — not a chain of wrappers. We verify via a probe that
    asks the subprocess to report whether the wrapper is marked.
    """
    reg, tmp = tool_registry

    code = (
        "with open('/tmp/awp_idemp_probe.txt', 'w') as f:\n"
        "    f.write('x')\n"
        "import builtins as _b\n"
        "print('WRAPPED=' + str(getattr(_b.open, '_awp_wrapped', False)))\n"
        "print('REAL_STORED=' + str(hasattr(_b, '_awp_real_open')))\n"
    )

    for _ in range(3):
        result = reg.call("code.execute", {"code": code})
        assert result["ok"], result.get("error")

    stdout = result["data"]["stdout"]
    assert "WRAPPED=True" in stdout, stdout
    assert "REAL_STORED=True" in stdout, stdout


def test_bytes_through_text_mode_still_works(tool_registry):
    """The proxy's bytes-escape-hatch (LLM opens 'w' and writes bytes)
    must continue to work after the idempotent-wrap fix — this was the
    original reason for the monkey-patch.
    """
    reg, tmp = tool_registry
    target = tmp / "image.bin"

    code = f"""
# Open in text mode then write bytes — the proxy must detect this and
# transparently reopen in binary mode.
with open({str(target)!r}, 'w') as f:
    f.write(b'\\x89PNG\\r\\n\\x1a\\nfakepngbytes')
print('done')
"""
    result = reg.call("code.execute", {"code": code})
    assert result["ok"], result.get("error")
    assert target.exists()
    # File should contain PNG magic bytes thanks to the proxy's bytes escape.
    assert target.read_bytes().startswith(b"\x89PNG")
