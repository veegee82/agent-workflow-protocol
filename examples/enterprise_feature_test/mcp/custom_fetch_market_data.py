"""
Custom MCP Tool: custom.fetch_market_data

Fiktives Tool zum Abrufen von Marktdaten über eine externe API.
Demonstriert Custom MCP Tools (F6) und Secret Injection.

Rules:
  CT1: Filename does not start with underscore ✓
  CT2: Namespace 'custom' is not reserved ✓
  CT3: Tool name from decorator ✓
  CT4: Standard return format ✓
  CT5: FastMCP stub included ✓
  CT6: All parameters typed ✓
  CT7: app = FastMCP("custom") ✓
"""

from __future__ import annotations

from typing import Any, Dict


class FastMCP:
    """AWP-compatible tool registry stub."""

    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self, _name: str, *, secrets: list[str] | None = None):
        def _decorator(fn):
            fn._awp_secrets = secrets or []
            return fn

        return _decorator


app = FastMCP("custom")


@app.tool("custom.fetch_market_data", secrets=["MARKET_DATA_API_KEY"])
def fetch_market_data(
    *,
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    include_volume: bool = True,
    _secrets: dict = {},
) -> Dict[str, Any]:
    """Fetch market data (OHLCV) for a given symbol and timeframe.

    Args:
        symbol: Trading pair or ticker symbol (e.g., "BTCUSD", "AAPL").
        timeframe: Candle timeframe (e.g., "1m", "5m", "1h", "1d").
        limit: Number of candles to fetch (max 500).
        include_volume: Whether to include volume data.
        _secrets: Injected by AWP runtime. Contains MARKET_DATA_API_KEY.

    Returns:
        Standardized AWP tool result with OHLCV data.
    """
    try:
        api_key = _secrets.get("MARKET_DATA_API_KEY", "")

        if not api_key:
            return {
                "ok": False,
                "status": 401,
                "data": {},
                "error": "MARKET_DATA_API_KEY not configured in secrets.yaml",
            }

        if limit > 500:
            limit = 500

        # --- Simulated market data (replace with real API call) ---
        import random
        import datetime

        base_price = 67500.0 if "BTC" in symbol.upper() else 185.0
        candles = []
        for i in range(limit):
            ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
                hours=limit - i
            )
            open_price = base_price + random.uniform(-500, 500)
            high_price = open_price + random.uniform(0, 300)
            low_price = open_price - random.uniform(0, 300)
            close_price = random.uniform(low_price, high_price)
            volume = random.uniform(100, 5000) if include_volume else None

            candle = {
                "timestamp": ts.isoformat(),
                "open": round(open_price, 2),
                "high": round(high_price, 2),
                "low": round(low_price, 2),
                "close": round(close_price, 2),
            }
            if include_volume:
                candle["volume"] = round(volume, 2)

            candles.append(candle)
            base_price = close_price

        result = {
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "candle_count": len(candles),
            "candles": candles,
            "source": "custom_market_data_api",
            "api_version": "v2",
        }

        return {
            "ok": True,
            "status": 200,
            "data": result,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 500,
            "data": {},
            "error": str(e),
        }
