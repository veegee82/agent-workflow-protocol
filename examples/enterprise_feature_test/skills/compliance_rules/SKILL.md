# Compliance & Governance Regeln

Dieses Skill-Dokument definiert die regulatorischen Anforderungen und
Governance-Regeln für den Enterprise-Workflow.

## Datenhandhabung

### Klassifizierung

| Stufe | Bezeichnung | Beispiele | Behandlung |
|-------|------------|-----------|-----------|
| C0 | Öffentlich | Marktpreise, Indizes | Frei verwendbar |
| C1 | Intern | Berechnete Metriken, Analysen | Nur innerhalb des Workflows |
| C2 | Vertraulich | API-Keys, Signing-Keys | Nur via Secrets-Injection |
| C3 | Streng vertraulich | Personendaten, Kontostände | Nicht speichern, nicht loggen |

### Regeln

1. **R-SEC-01**: Secrets (C2) dürfen **niemals** in Logs, Outputs oder Memory erscheinen.
2. **R-SEC-02**: Das LLM sieht **keine** Secret-Werte — nur die Tool-Implementierung hat Zugriff.
3. **R-SEC-03**: Alle Tool-Aufrufe werden im Audit-Log protokolliert (mit Hash-Chain).
4. **R-SEC-04**: `shell.execute` ist für den `report_writer` durch Access Control blockiert.

## Rate Limiting

- Maximal **120 Tool-Aufrufe pro Minute** pro Agent.
- Bei Überschreitung: Agent wird für 5 Sekunden gedrosselt (429 Too Many Requests).
- Circuit Breaker öffnet nach **3 aufeinanderfolgenden Fehlern**.
- Reset nach **30 Sekunden** im Half-Open-Modus (1 Test-Call erlaubt).

## Audit Trail

Jeder Workflow-Durchlauf erzeugt einen Audit-Eintrag mit:

```json
{
  "run_id": "uuid",
  "timestamp": "ISO-8601",
  "agents_executed": ["agent_id", ...],
  "tool_calls": [
    {
      "agent": "agent_id",
      "tool": "namespace.action",
      "status": 200,
      "duration_ms": 42,
      "hash": "sha256:..."
    }
  ],
  "governance_events": [
    {
      "type": "access_denied|rate_limited|circuit_open",
      "agent": "agent_id",
      "tool": "namespace.action",
      "reason": "..."
    }
  ],
  "hash_chain_valid": true
}
```

## Report-Signierung

Der finale Report wird mit einem SHA-256-Hash signiert:

1. Report-Content wird als UTF-8 gelesen.
2. `REPORT_SIGNING_KEY` wird aus `secrets.yaml` geladen.
3. HMAC-SHA256 wird über Content + Key berechnet.
4. Hash wird als `sha256:<hex>` im Output gespeichert.

## Observability-Anforderungen

- **Tracing**: W3C Trace Context Propagation über alle Agents hinweg.
- **Metriken**: Token-Verbrauch, Tool-Call-Dauer, Konfidenz-Verteilung.
- **Logging**: Strukturierte JSON-Logs auf stdout (Level: debug für Test-Workflow).
- **Sampling**: 100% für diesen Test-Workflow (in Produktion: anpassen).
