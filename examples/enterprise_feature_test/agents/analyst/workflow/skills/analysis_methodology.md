# Analyse-Methodik

## Vorgehensweise

1. **Daten sichten**: Lies die vorverarbeiteten Daten aus dem Preprocessor-Output.
2. **Historischen Kontext laden**: Durchsuche das Memory nach früheren Analysen.
3. **Faktoren berechnen**: Berechne die drei Risikofaktoren mit den Arithmetic-Tools.
4. **Gewichten und kombinieren**: Wende die Gewichte aus dem Market-Analysis-Skill an.
5. **Vergleichen**: Stelle den aktuellen Risk Score dem letzten gespeicherten gegenüber.
6. **Empfehlungen ableiten**: Basierend auf der Risiko-Schwelle Handlungsempfehlungen generieren.
7. **Speichern**: Schreibe die Analyse ins Memory für zukünftige Vergleiche.

## Preprocessor-Integration

Deine Eingabedaten durchlaufen zwei Schritte:

| Schritt | Script | Input | Output |
|---------|--------|-------|--------|
| 1. Normalisierung | `normalize.py` | Rohdaten vom Data Collector | ATR-normalisierte Werte, Z-Scores |
| 2. Feature-Extraktion | `features.py` | Normalisierte Daten | Trend-Labels, Volatilitäts-Klassen |

Die Features werden als zusätzlicher Kontext in deinen Prompt injiziert.

## Memory-Nutzung

- **Lesen**: `memory.search` mit Keywords wie "risk_score", "analysis", "trend"
- **Schreiben**: Speichere nach jeder Analyse: Datum, Risk Score, Trend, Empfehlungen
- **Kuratieren**: Triggere `memory.curate` wenn die täglichen Logs > 7 Tage alt sind
