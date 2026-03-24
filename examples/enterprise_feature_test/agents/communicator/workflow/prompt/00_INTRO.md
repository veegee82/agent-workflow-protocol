# Aufgabe: Ergebnisse konsolidieren und kommunizieren

Du erhältst Ergebnisse aus zwei parallelen Agents:

**Code Executor:**
- `computed_metrics`: {{code_executor.computed_metrics}}
- `execution_log`: {{code_executor.execution_log}}

**Analyst:**
- `analysis_summary`: {{analyst.analysis_summary}}
- `risk_score`: {{analyst.risk_score}}
- `recommendations`: {{analyst.recommendations}}

**Aufgaben:**
1. Konsolidiere beide Ergebnisse zu einem Gesamtbericht
2. Sende den Bericht über den `default`-Channel an `report_writer`
3. Sende Metriken über den `metrics`-Channel an `report_writer`
4. Falls risk_score > 0.7: Sende Broadcast-Alert über `alerts`-Channel
5. Prüfe eingehende Nachrichten via `agent.list_messages`

Antworte als JSON gemäß deinem Output Schema.
