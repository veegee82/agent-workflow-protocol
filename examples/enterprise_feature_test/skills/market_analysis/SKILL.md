# Marktanalyse-Methodik

Du nutzt eine strukturierte Methodik für die Analyse von Marktdaten.

## Analyse-Framework

### 1. Technische Analyse

- **Trendbestimmung**: Nutze EMA-Stacks (9/21/50/100/200) zur Trendidentifikation.
  - Bullish: Preis > EMA9 > EMA21 > EMA50 (Golden Alignment)
  - Bearish: Preis < EMA9 < EMA21 < EMA50 (Death Alignment)
  - Neutral: EMAs verschränkt, kein klares Signal

- **Marktstruktur**: Identifiziere BOS (Break of Structure) und CHoCH (Change of Character).
  - BOS: Bestätigung des laufenden Trends
  - CHoCH: Mögliche Trendumkehr

- **Volatilität**: ATR (Average True Range) als Maß für Marktvolatilität.
  - Low: ATR < 1% des Preises
  - Medium: ATR 1-3% des Preises
  - High: ATR > 3% des Preises

### 2. Risikobewertung

Der Risk Score wird aus drei Faktoren berechnet:

```
risk_score = w1 * volatility_factor + w2 * trend_factor + w3 * structure_factor
```

| Faktor | Gewicht | Beschreibung |
|--------|---------|-------------|
| Volatilität | 0.35 | Normalisierte ATR-basierte Volatilität |
| Trend | 0.35 | Stärke und Klarheit des aktuellen Trends |
| Struktur | 0.30 | Marktstruktur-Integrität (BOS/CHoCH) |

### 3. Handlungsempfehlungen

Priorisierung basierend auf Risk Score:

| Risk Score | Priorität | Aktion |
|-----------|-----------|--------|
| > 0.7 | HIGH | Risiko reduzieren, Positionen absichern |
| 0.4 - 0.7 | MEDIUM | Vorsichtig agieren, Stop-Losses anpassen |
| < 0.4 | LOW | Normal weiterarbeiten, Chancen nutzen |

## Datenquellen-Bewertung

Bewerte jede Datenquelle nach:
- **Aktualität**: Wie alt sind die Daten? (< 1h = optimal, > 24h = veraltet)
- **Verlässlichkeit**: Bekannte vs. unbekannte Quelle
- **Vollständigkeit**: Fehlende Felder reduzieren die Qualität
