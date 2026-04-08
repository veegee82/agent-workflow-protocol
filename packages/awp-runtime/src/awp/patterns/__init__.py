"""AWP Pattern Library — verified, reusable tool skeletons.

Patterns are deterministic templates for tools that the runtime can
instantiate without LLM generation. Each pattern carries:

  - id              short stable identifier (e.g. "pandas_csv_read")
  - description     one-line purpose
  - capability      semantic capability tag used by R31 plan-tool-closure
  - packages        pip packages required to run the tool body
  - signature       declared (input_name -> type_str) for the handler
  - skeleton        Python source for a complete handler() function
  - smoke_test      Python snippet that exercises the handler in a venv

The library is consumed by:

  1. The PLAN-phase prompt (so the manager sees a compact "available
     patterns" table and can mark capabilities as `reuse` instead of
     `generate`).

  2. The R31 plan-tool-closure validator (which checks that any capability
     marked `reuse` references a pattern that actually exists here).

  3. The tool-skeleton generator (B2) which prefers an instantiated
     pattern over a freshly synthesised skeleton.

Patterns are intentionally tiny and dependency-light. The starter set
covers the recurring shapes observed in real delegation-loop runs:
numpy compute, pandas tabular IO, PDF report writing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# New archetype + recipe layer (see archetype.py / recipe.py).
from .archetype import (  # noqa: F401
    ARCHETYPES,
    Archetype,
    COMPUTE,
    FETCH,
    PARSE,
    PROBE,
    RENDER,
    TRANSFORM,
    archetype_capability_families,
    get_archetype,
    list_archetypes,
    render_archetype_index,
)
from .recipe import (  # noqa: F401
    Recipe,
    RecipeStore,
    TrustLevel,
    capture_recipe,
    compute_recipe_id,
    replay_gate,
)


@dataclass(frozen=True)
class Pattern:
    """A verified, reusable tool template."""

    id: str
    description: str
    capability: str
    packages: tuple[str, ...]
    signature: dict[str, str]
    skeleton: str
    smoke_test: str
    output_keys: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# numpy: array statistics
# ---------------------------------------------------------------------------
NUMPY_STATS = Pattern(
    id="numpy_array_stats",
    description="Compute basic statistics (mean, std, min, max) over a numeric list using numpy.",
    capability="numpy_stats",
    packages=("numpy",),
    signature={"values": "list[float]"},
    output_keys=("mean", "std", "min", "max", "count", "confidence"),
    skeleton='''def handler(*, values, **_):
    """Compute basic numpy statistics over a numeric list."""
    import numpy as np
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return {
            "ok": False,
            "status": 400,
            "data": {},
            "error": "values must be non-empty",
        }
    return {
        "ok": True,
        "status": 200,
        "data": {
            "mean": float(arr.mean()),
            "std": float(arr.std(ddof=0)),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "count": int(arr.size),
            "confidence": 1.0,
        },
        "error": None,
    }
''',
    smoke_test='''
result = handler(values=[1.0, 2.0, 3.0, 4.0])
assert result["ok"] is True, f"expected ok, got {result}"
assert result["data"]["count"] == 4
assert abs(result["data"]["mean"] - 2.5) < 1e-9
print("PATTERN_OK numpy_array_stats")
''',
)


# ---------------------------------------------------------------------------
# pandas: read a CSV and return descriptive summary
# ---------------------------------------------------------------------------
PANDAS_CSV_SUMMARY = Pattern(
    id="pandas_csv_summary",
    description="Read a CSV file with pandas and return shape, columns, and per-column dtypes + numeric describe().",
    capability="pandas_csv_summary",
    packages=("pandas",),
    signature={"path": "str"},
    output_keys=("rows", "cols", "columns", "dtypes", "describe", "confidence"),
    skeleton='''def handler(*, path, **_):
    """Summarise a CSV file using pandas."""
    import pandas as pd
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        return {"ok": False, "status": 404, "data": {}, "error": f"file not found: {path}"}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "status": 400, "data": {}, "error": f"read_csv failed: {exc}"}
    describe = {}
    num = df.select_dtypes(include="number")
    if not num.empty:
        describe = {col: {k: float(v) for k, v in num[col].describe().items()} for col in num.columns}
    return {
        "ok": True,
        "status": 200,
        "data": {
            "rows": int(df.shape[0]),
            "cols": int(df.shape[1]),
            "columns": list(map(str, df.columns)),
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "describe": describe,
            "confidence": 1.0,
        },
        "error": None,
    }
''',
    smoke_test='''
import tempfile, os
csv = "a,b\\n1,2\\n3,4\\n5,6\\n"
tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
tmp.write(csv); tmp.close()
try:
    result = handler(path=tmp.name)
    assert result["ok"] is True, f"expected ok, got {result}"
    assert result["data"]["rows"] == 3
    assert result["data"]["cols"] == 2
    assert result["data"]["columns"] == ["a", "b"]
    print("PATTERN_OK pandas_csv_summary")
finally:
    os.unlink(tmp.name)
''',
)


# ---------------------------------------------------------------------------
# pdf: write a simple text report to PDF using reportlab
# ---------------------------------------------------------------------------
PDF_TEXT_REPORT = Pattern(
    id="pdf_text_report",
    description="Write a multi-line text report to a PDF file using reportlab.",
    capability="pdf_text_report",
    packages=("reportlab",),
    signature={"path": "str", "title": "str", "body": "str"},
    output_keys=("path", "size_bytes", "confidence"),
    skeleton='''def handler(*, path, title, body, **_):
    """Render a simple text PDF using reportlab."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 740, str(title)[:120])
    c.setFont("Helvetica", 11)
    y = 710
    for line in str(body).splitlines() or [""]:
        if y < 72:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = 740
        c.drawString(72, y, line[:110])
        y -= 14
    c.save()
    import os
    size = os.path.getsize(path)
    return {
        "ok": True,
        "status": 200,
        "data": {"path": path, "size_bytes": int(size), "confidence": 1.0},
        "error": None,
    }
''',
    smoke_test='''
import tempfile, os
out = os.path.join(tempfile.mkdtemp(), "report.pdf")
result = handler(path=out, title="Test Report", body="Line one\\nLine two\\nLine three")
assert result["ok"] is True, f"expected ok, got {result}"
assert os.path.exists(out)
assert result["data"]["size_bytes"] > 200
print("PATTERN_OK pdf_text_report")
''',
)


# ---------------------------------------------------------------------------
# matplotlib: line plot to PNG (replaces ad-hoc plot generation that
# repeatedly produced 5-byte placeholder PNGs in real BTC runs).
# ---------------------------------------------------------------------------
MATPLOTLIB_LINE_PLOT_PNG = Pattern(
    id="matplotlib_line_plot_png",
    description="Render one or two line series to a PNG file using matplotlib (Agg backend, no display required).",
    capability="line_plot_png",
    packages=("matplotlib",),
    signature={
        "path": "str",
        "x": "list[float]",
        "y_primary": "list[float]",
        "y_secondary": "list[float] | None",
        "title": "str",
        "ylabel": "str",
    },
    output_keys=("path", "size_bytes", "n_points", "confidence"),
    skeleton='''def handler(*, path, x, y_primary, y_secondary=None, title="", ylabel="", **_):
    """Render a 1- or 2-series line plot to PNG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import os

    if not x or not y_primary:
        return {"ok": False, "status": 400, "data": {}, "error": "x and y_primary must be non-empty"}
    if len(x) != len(y_primary):
        return {"ok": False, "status": 400, "data": {}, "error": f"len(x)={len(x)} != len(y_primary)={len(y_primary)}"}

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.plot(x, y_primary, color="tab:blue", label=ylabel or "primary")
    ax1.set_title(title or "")
    ax1.set_ylabel(ylabel or "")
    ax1.grid(True, alpha=0.3)

    if y_secondary is not None and len(y_secondary) == len(x):
        ax2 = ax1.twinx()
        ax2.plot(x, y_secondary, color="tab:red", alpha=0.7, label="secondary")
        ax2.set_ylabel("secondary")

    fig.tight_layout()
    fig.savefig(path, dpi=120, format="png")
    plt.close(fig)

    size = os.path.getsize(path)
    if size < 1000:
        return {"ok": False, "status": 500, "data": {"path": path, "size_bytes": int(size)},
                "error": f"PNG suspiciously small ({size} bytes) — render likely failed"}
    return {
        "ok": True,
        "status": 200,
        "data": {"path": path, "size_bytes": int(size), "n_points": int(len(x)), "confidence": 1.0},
        "error": None,
    }
''',
    smoke_test='''
import tempfile, os
out = os.path.join(tempfile.mkdtemp(), "plot.png")
xs = list(range(30))
ys = [v * 1.5 + 10 for v in xs]
zs = [-(v * 0.3) for v in xs]
result = handler(path=out, x=xs, y_primary=ys, y_secondary=zs, title="t", ylabel="price")
assert result["ok"] is True, f"expected ok, got {result}"
assert os.path.exists(out)
assert result["data"]["size_bytes"] > 2000
print("PATTERN_OK matplotlib_line_plot_png")
''',
)


# ---------------------------------------------------------------------------
# markdown report writer: structured key-value section + freeform body.
# ---------------------------------------------------------------------------
MARKDOWN_REPORT_WRITER = Pattern(
    id="markdown_report_writer",
    description="Write a markdown report with a title, key-value metrics table, and freeform body.",
    capability="markdown_report",
    packages=(),
    signature={
        "path": "str",
        "title": "str",
        "metrics": "dict[str, Any]",
        "body": "str",
    },
    output_keys=("path", "size_bytes", "confidence"),
    skeleton='''def handler(*, path, title, metrics=None, body="", **_):
    """Write a structured markdown report file."""
    import os
    metrics = metrics or {}
    lines = [f"# {title}", ""]
    if metrics:
        lines.append("## Metrics")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("|---|---|")
        for k, v in metrics.items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
    if body:
        lines.append("## Summary")
        lines.append("")
        lines.append(str(body))
    text = "\\n".join(lines) + "\\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    size = os.path.getsize(path)
    return {
        "ok": True,
        "status": 200,
        "data": {"path": path, "size_bytes": int(size), "confidence": 1.0},
        "error": None,
    }
''',
    smoke_test='''
import tempfile, os
out = os.path.join(tempfile.mkdtemp(), "report.md")
result = handler(path=out, title="BTC Report", metrics={"mean": 0.01, "vol": 0.5, "max_dd": -0.2}, body="Bullish trend.")
assert result["ok"] is True, f"expected ok, got {result}"
assert os.path.exists(out)
content = open(out).read()
assert "BTC Report" in content and "mean" in content
print("PATTERN_OK markdown_report_writer")
''',
)


# ---------------------------------------------------------------------------
# CoinGecko OHLC fetch with daily aggregation. The CoinGecko /ohlc
# endpoint at days=30 returns 4-HOUR candles (180 rows), NOT daily.
# This pattern aggregates to daily candles automatically — encoding the
# domain quirk that previously cost multiple repair iterations in real
# runs.
# ---------------------------------------------------------------------------
COINGECKO_OHLC_DAILY = Pattern(
    id="coingecko_ohlc_daily",
    description="Fetch CoinGecko /ohlc for a coin and aggregate intra-day candles into daily OHLC. Knows that days=30 returns 4-hour candles.",
    capability="coingecko_ohlc_daily",
    packages=("requests",),
    signature={
        "coin_id": "str",
        "vs_currency": "str",
        "days": "int",
    },
    output_keys=("rows", "first_ts", "last_ts", "candles", "confidence"),
    skeleton='''def handler(*, coin_id="bitcoin", vs_currency="usd", days=30, **_):
    """Fetch CoinGecko /ohlc and aggregate to DAILY candles.

    NOTE: CoinGecko returns intra-day candles for days<=90:
        days <=  1   -> 30-min candles
        days <=  7   -> 4-hour candles
        days <= 30   -> 4-hour candles  (180 rows for days=30)
        days > 30    -> 4-day candles
    This handler aggregates them to DAILY rows so callers can rely on
    one row per UTC day regardless of the input window.
    """
    import requests
    from datetime import datetime, timezone

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    try:
        resp = requests.get(url, params={"vs_currency": vs_currency, "days": days}, timeout=20)
    except Exception as exc:
        return {"ok": False, "status": 502, "data": {}, "error": f"network error: {exc}"}
    if resp.status_code != 200:
        return {"ok": False, "status": resp.status_code, "data": {}, "error": f"coingecko HTTP {resp.status_code}: {resp.text[:200]}"}
    raw = resp.json()
    if not isinstance(raw, list) or not raw:
        return {"ok": False, "status": 502, "data": {}, "error": "coingecko returned empty payload"}

    # Aggregate to daily UTC candles. Each row is [ts_ms, o, h, l, c].
    by_day: dict[str, list[float]] = {}
    order: list[str] = []
    for row in raw:
        if not (isinstance(row, list) and len(row) == 5):
            continue
        ts_ms, o, h, l, c = row
        day = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if day not in by_day:
            by_day[day] = [float(o), float(h), float(l), float(c)]
            order.append(day)
        else:
            agg = by_day[day]
            agg[1] = max(agg[1], float(h))
            agg[2] = min(agg[2], float(l))
            agg[3] = float(c)  # last close of the day

    candles = [
        {"date": d, "open": by_day[d][0], "high": by_day[d][1], "low": by_day[d][2], "close": by_day[d][3]}
        for d in order
    ]
    return {
        "ok": True,
        "status": 200,
        "data": {
            "rows": int(len(candles)),
            "first_ts": order[0] if order else None,
            "last_ts": order[-1] if order else None,
            "candles": candles,
            "confidence": 1.0,
        },
        "error": None,
    }
''',
    smoke_test='''
# Smoke test does NOT hit the live network — patches requests.get with a
# fixture so the gate stays deterministic and offline-safe.
import sys, types
fake = types.SimpleNamespace()
class _R:
    status_code = 200
    text = ""
    def json(self):
        # 6 candles of 4-hour granularity over 1 day, then 6 more over day 2
        from datetime import datetime, timezone, timedelta
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = []
        for i in range(12):
            ts = int((base + timedelta(hours=i*4)).timestamp() * 1000)
            rows.append([ts, 100+i, 105+i, 95+i, 102+i])
        return rows
def _get(url, params=None, timeout=None):
    return _R()
fake.get = _get
sys.modules["requests"] = fake
result = handler(coin_id="bitcoin", days=1)
assert result["ok"] is True, f"expected ok, got {result}"
assert result["data"]["rows"] == 2, f"expected 2 daily rows, got {result['data']['rows']}"
assert result["data"]["candles"][0]["high"] >= 105
print("PATTERN_OK coingecko_ohlc_daily")
''',
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
PATTERNS: dict[str, Pattern] = {
    p.id: p
    for p in (
        NUMPY_STATS,
        PANDAS_CSV_SUMMARY,
        PDF_TEXT_REPORT,
        MATPLOTLIB_LINE_PLOT_PNG,
        MARKDOWN_REPORT_WRITER,
        COINGECKO_OHLC_DAILY,
    )
}


def list_patterns() -> list[Pattern]:
    """Return all registered patterns in stable order."""
    return list(PATTERNS.values())


def get_pattern(pattern_id: str) -> Pattern | None:
    return PATTERNS.get(pattern_id)


def known_capabilities() -> set[str]:
    """Capability tags that are satisfied by some pattern OR archetype family.

    R31 (plan-tool-closure) treats both as planable: a recipe satisfies
    a capability directly, an archetype family signals that the runtime
    can synthesise one on demand. This decouples planning from library
    size — the manager plans against AWP's structural reach, not just
    against what happens to be in the library today.
    """
    seeded = {p.capability for p in PATTERNS.values()}
    return seeded | archetype_capability_families()


def render_index_for_prompt() -> str:
    """Compact human-readable index for inclusion in the manager system prompt.

    Two sections: archetypes (what AWP can structurally do) come first,
    concrete patterns (already-verified shortcuts) come second.
    """
    lines = ["### Archetypes (composable building blocks)", ""]
    lines.append(render_archetype_index())
    lines.append("")
    lines.append("### Concrete patterns (verified shortcuts — prefer these when they fit)")
    lines.append("")
    lines.append("| pattern_id | capability | description | inputs |")
    lines.append("|---|---|---|---|")
    for p in list_patterns():
        sig = ", ".join(f"{k}: {v}" for k, v in p.signature.items())
        lines.append(f"| `{p.id}` | `{p.capability}` | {p.description} | {sig} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adapter: legacy Pattern → Recipe (so the recipe pipeline can list seeds)
# ---------------------------------------------------------------------------

# Map legacy seed patterns to the archetype that would express them today.
# Used by `seed_recipes()` so the recipe ecosystem (replay-gate, capture,
# capability lookup) sees the seeds as first-class recipes — even though
# their handler bodies are still the hand-written legacy skeletons.
_SEED_PATTERN_ARCHETYPES: dict[str, str] = {
    "numpy_array_stats":       "compute",
    "pandas_csv_summary":      "parse",
    "pdf_text_report":         "render",
    "matplotlib_line_plot_png": "render",
    "markdown_report_writer":  "render",
    "coingecko_ohlc_daily":    "fetch",
}


def seed_recipes() -> list[Recipe]:
    """Return the 6 hand-written seed patterns as Recipe instances.

    Each carries ``legacy_skeleton`` so it renders byte-identically to
    the pre-archetype implementation, while still participating in the
    recipe trust/replay ecosystem (already TRUSTED — they ship with
    the runtime).
    """
    out: list[Recipe] = []
    for pat in list_patterns():
        arch_id = _SEED_PATTERN_ARCHETYPES.get(pat.id, "compute")
        arch = get_archetype(arch_id)
        rid = compute_recipe_id(arch_id, arch.version if arch else 1, {"_seed": pat.id})
        out.append(
            Recipe(
                id=rid,
                archetype_id=arch_id,
                archetype_version=arch.version if arch else 1,
                capability=pat.capability,
                description=pat.description,
                params={"_seed": pat.id},
                smoke_test=pat.smoke_test,
                smoke_packages=pat.packages,
                source="seeded",
                trust=TrustLevel.TRUSTED,
                success_count=PROMOTE_PROBATIONARY_AT_PUBLIC,
                legacy_skeleton=pat.skeleton,
                legacy_signature=dict(pat.signature),
                legacy_output_keys=pat.output_keys,
            )
        )
    return out


# Re-export the promotion threshold under a stable public name so seed
# recipes can declare themselves "already trusted" without importing
# a private constant from .recipe.
from .recipe import PROMOTE_PROBATIONARY_AT as PROMOTE_PROBATIONARY_AT_PUBLIC  # noqa: E402


__all__ = [
    # Legacy
    "Pattern",
    "PATTERNS",
    "list_patterns",
    "get_pattern",
    "known_capabilities",
    "render_index_for_prompt",
    # Archetypes
    "Archetype",
    "ARCHETYPES",
    "get_archetype",
    "list_archetypes",
    "archetype_capability_families",
    "render_archetype_index",
    # Recipes
    "Recipe",
    "RecipeStore",
    "TrustLevel",
    "compute_recipe_id",
    "capture_recipe",
    "replay_gate",
    "seed_recipes",
]
