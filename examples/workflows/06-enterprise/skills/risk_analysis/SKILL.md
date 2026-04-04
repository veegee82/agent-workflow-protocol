---
name: risk-analysis
domain: finance
scope: project
version: "1.0"
---

# Risk Analysis

## Purpose

Classify and score business risks so agents produce consistent, comparable assessments.

## Concepts

- **Operational Risk**: Risks from internal processes, people, and systems failures.
- **Market Risk**: Risks from market movements, price volatility, and economic shifts.
- **Credit Risk**: Risks from counterparty defaults or inability to meet obligations.
- **Compliance Risk**: Risks from regulatory non-compliance or policy violations.
- **Risk Score**: A normalized 0.0-1.0 value derived from likelihood × impact.

## Rules

1. Categorize every identified risk into exactly one of the four categories above.
2. Use quantitative metrics where possible — avoid purely qualitative labels.
3. Express risk scores as normalized 0.0-1.0 values (likelihood × impact / 25).
4. Document all assumptions explicitly — flag any assumption lacking data support.
5. Cross-reference findings with historical data when available.

## Procedure

1. Identify risk events from the input data.
2. Classify each event into Operational, Market, Credit, or Compliance.
3. Rate likelihood (1-5 scale) and impact (1-5 scale).
4. Compute risk score: (likelihood × impact) / 25.
5. Rank risks by score, highest first.

## Examples

### Example 1: Vendor dependency

**Input:**
```
Single cloud provider hosts all production systems. No failover contract.
```

**Output:**
```json
{
  "category": "operational",
  "event": "Single-vendor cloud dependency without failover",
  "likelihood": 3,
  "impact": 5,
  "risk_score": 0.60,
  "classification": "high",
  "assumption": "Based on industry average cloud outage frequency of 2-3 incidents/year"
}
```
