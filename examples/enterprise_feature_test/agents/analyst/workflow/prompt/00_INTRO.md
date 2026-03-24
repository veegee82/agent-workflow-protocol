# Aufgabe: Marktanalyse durchführen

Analysiere die gesammelten und vorverarbeiteten Marktdaten.

**Eingabedaten:**
- `raw_data`: {{data_collector.raw_data}}
- `data_sources`: {{data_collector.data_sources}}

**Preprocessor-Output:**
Die Daten wurden bereits normalisiert (ATR, Z-Score) und Features extrahiert
(Trend-Labels, Volatilitäts-Klassen, Momentum).

**Aufgaben:**
1. Durchsuche das Memory nach früheren Analysen (`memory.search`)
2. Berechne den Risk Score basierend auf mindestens 3 Faktoren
3. Leite Handlungsempfehlungen mit Prioritäten ab
4. Vergleiche mit historischen Daten aus dem Memory
5. Speichere deine Analyse im Memory für zukünftige Vergleiche

Antworte als JSON gemäß deinem Output Schema.
