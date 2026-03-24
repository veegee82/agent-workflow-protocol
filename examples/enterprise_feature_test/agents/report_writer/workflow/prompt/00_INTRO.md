# Aufgabe: Finalen Report erstellen

Du erhältst den konsolidierten Bericht vom Communicator.

**Eingabedaten:**
- `consolidated_report`: {{communicator.consolidated_report}}
- `broadcast_status`: {{communicator.broadcast_status}}
- `risk_score`: {{analyst.risk_score}}

**Bedingte Ausführung:** Du wirst nur ausgeführt, wenn `risk_score > 0.3`.

**Aufgaben:**
1. Erstelle einen vollständigen Markdown-Report (min. 500 Wörter)
2. Speichere den Report unter `data/output/report_{{TIMESTAMP}}.md`
3. Berechne den SHA-256-Hash des Reports
4. **Governance-Test:** Versuche `shell.execute` aufzurufen (wird blockiert)
5. Dokumentiere alle Governance-Events im `governance_log`
6. Speichere Report-Metadaten im Memory

Antworte als JSON gemäß deinem Output Schema.
