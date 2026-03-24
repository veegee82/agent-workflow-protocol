# Aufgabe: Metriken berechnen (Code Mode)

Du erhältst Rohdaten vom Data Collector. Schreibe TypeScript-Code, der
statistische Metriken aus diesen Daten berechnet.

**Eingabedaten:**
- `raw_data`: {{data_collector.raw_data}}
- `data_sources`: {{data_collector.data_sources}}

Schreibe eine async function, die das AWP Tool SDK verwendet, um:
1. Die Rohdaten zu laden und zu parsen
2. Mean, Median, StdDev, Trend und Momentum zu berechnen
3. Die Ergebnisse unter `data/output/metrics.json` zu speichern

Antworte als JSON gemäß deinem Output Schema.
