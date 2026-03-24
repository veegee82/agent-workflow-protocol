"""
Preprocessor Step 1: normalize_market_data

Normalisiert Rohdaten aus dem Data Collector:
- ATR-Normalisierung der Preiswerte
- Z-Score-Berechnung für Vergleichbarkeit
- Auffüllen fehlender Werte (Forward Fill)

Input:  raw_data (dict) aus dem Data Collector Output
Output: Normalisierte Daten als dict mit zusätzlichen Feldern
"""

from __future__ import annotations

import math
from typing import Any, Dict, List


def run(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize market data for LLM consumption.

    Args:
        raw_data: Raw data from data_collector agent.

    Returns:
        Normalized data dict with additional fields.
    """
    candles = raw_data.get("candles", [])
    if not candles:
        return {
            "normalized": [],
            "atr": 0.0,
            "z_scores": [],
            "missing_values_filled": 0,
            "status": "no_data",
        }

    # --- Forward Fill missing values ---
    missing_count = 0
    prev = None
    for candle in candles:
        for field in ["open", "high", "low", "close"]:
            if candle.get(field) is None:
                if prev and prev.get(field) is not None:
                    candle[field] = prev[field]
                    missing_count += 1
                else:
                    candle[field] = 0.0
                    missing_count += 1
        prev = candle

    # --- Calculate ATR (Average True Range) ---
    true_ranges: List[float] = []
    for i in range(1, len(candles)):
        high = candles[i].get("high", 0)
        low = candles[i].get("low", 0)
        prev_close = candles[i - 1].get("close", 0)

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    atr = sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    # --- ATR-Normalize close prices ---
    close_prices = [c.get("close", 0) for c in candles]
    if atr > 0:
        normalized = [(p - close_prices[0]) / atr for p in close_prices]
    else:
        normalized = [0.0] * len(close_prices)

    # --- Z-Score calculation ---
    mean_price = sum(close_prices) / len(close_prices) if close_prices else 0
    variance = (
        sum((p - mean_price) ** 2 for p in close_prices) / len(close_prices)
        if close_prices
        else 0
    )
    stddev = math.sqrt(variance) if variance > 0 else 1.0
    z_scores = [(p - mean_price) / stddev for p in close_prices]

    return {
        "normalized": [round(v, 4) for v in normalized],
        "atr": round(atr, 4),
        "atr_percent": round((atr / mean_price * 100) if mean_price else 0, 4),
        "z_scores": [round(z, 4) for z in z_scores],
        "mean_price": round(mean_price, 2),
        "stddev": round(stddev, 4),
        "missing_values_filled": missing_count,
        "candle_count": len(candles),
        "status": "ok",
    }
