"""
Preprocessor Step 2: extract_features

Feature Engineering aus normalisierten Marktdaten:
- Trend-Labels (bullish/bearish/neutral) basierend auf Z-Score-Trend
- Volatilitäts-Klassen (low/medium/high) basierend auf ATR%
- Momentum-Wert als gewichteter Z-Score-Gradient

Input:  Normalisierte Daten aus Step 1 (normalize.py)
Output: Feature-Dict für LLM-Kontext-Injection
"""

from __future__ import annotations

from typing import Any, Dict, List


def run(normalized_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract features from normalized market data.

    Args:
        normalized_data: Output from normalize.py preprocessor step.

    Returns:
        Feature dict with trend labels, volatility classes, momentum.
    """
    z_scores = normalized_data.get("z_scores", [])
    atr_percent = normalized_data.get("atr_percent", 0.0)
    normalized = normalized_data.get("normalized", [])

    if not z_scores or len(z_scores) < 5:
        return {
            "trend_label": "neutral",
            "volatility_class": "low",
            "momentum": 0.0,
            "trend_strength": 0.0,
            "features_extracted": False,
            "reason": "Insufficient data points",
        }

    # --- Trend Label ---
    # Use last 20% of z-scores to determine trend
    lookback = max(5, len(z_scores) // 5)
    recent_z = z_scores[-lookback:]
    early_z = z_scores[:lookback]

    recent_avg = sum(recent_z) / len(recent_z)
    early_avg = sum(early_z) / len(early_z)
    z_delta = recent_avg - early_avg

    if z_delta > 0.5:
        trend_label = "bullish"
    elif z_delta < -0.5:
        trend_label = "bearish"
    else:
        trend_label = "neutral"

    # --- Trend Strength (0.0 - 1.0) ---
    trend_strength = min(abs(z_delta) / 2.0, 1.0)

    # --- Volatility Class ---
    if atr_percent < 1.0:
        volatility_class = "low"
    elif atr_percent < 3.0:
        volatility_class = "medium"
    else:
        volatility_class = "high"

    # --- Momentum (weighted Z-Score gradient) ---
    # Exponential weighting: recent values matter more
    if len(z_scores) >= 3:
        weights = [1.0 + (i / len(z_scores)) for i in range(len(z_scores))]
        gradients: List[float] = []
        for i in range(1, len(z_scores)):
            grad = (z_scores[i] - z_scores[i - 1]) * weights[i]
            gradients.append(grad)
        momentum = sum(gradients) / sum(weights[1:]) if weights[1:] else 0.0
        momentum = max(-1.0, min(1.0, momentum))  # Clamp to [-1, 1]
    else:
        momentum = 0.0

    # --- EMA Stack Labels (simplified) ---
    if len(normalized) >= 21:
        ema_9 = sum(normalized[-9:]) / 9
        ema_21 = sum(normalized[-21:]) / 21
        if ema_9 > ema_21:
            ema_alignment = "golden"
        elif ema_9 < ema_21:
            ema_alignment = "death"
        else:
            ema_alignment = "flat"
    else:
        ema_alignment = "insufficient_data"

    return {
        "trend_label": trend_label,
        "trend_strength": round(trend_strength, 4),
        "volatility_class": volatility_class,
        "momentum": round(momentum, 4),
        "ema_alignment": ema_alignment,
        "z_delta": round(z_delta, 4),
        "recent_z_avg": round(recent_avg, 4),
        "features_extracted": True,
        "lookback_period": lookback,
    }
