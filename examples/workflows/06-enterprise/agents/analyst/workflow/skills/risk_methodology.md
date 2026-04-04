---
name: risk-methodology
domain: finance
scope: agent
version: "1.0"
---

# Risk Assessment Methodology

## Purpose

Provide the analyst agent with a standardized scoring framework for risk assessment.

## Concepts

- **Likelihood**: Probability of an adverse event occurring (1-5 scale).
- **Impact**: Potential damage if the event occurs (1-5 scale).
- **Risk Score**: Normalized composite metric: (likelihood × impact) / 25, yielding 0.0-1.0.
- **Risk Bands**: Low (0.0-0.3), Medium (0.3-0.6), High (0.6-0.8), Critical (0.8-1.0).

## Rules

1. Always compute risk score as (likelihood × impact) / 25.
2. Classify every risk into exactly one band: Low, Medium, High, or Critical.
3. Consider both quantitative data and qualitative factors — but quantitative takes precedence when available.
4. Flag any data quality issues that may affect the assessment.
5. Document assumptions explicitly alongside each score.

## Procedure

1. Gather available data on the risk event.
2. Assess likelihood on the 1-5 scale using historical frequency or expert judgment.
3. Assess impact on the 1-5 scale using financial exposure or operational severity.
4. Calculate risk score and assign band.
5. Note confidence level and any data gaps.

## Examples

### Example 1: Supply chain disruption

**Input:**
```
Key supplier in region with political instability. 60% of components sourced there.
Historical disruption: 2 incidents in past 5 years.
```

**Output:**
```json
{
  "likelihood": 4,
  "impact": 4,
  "risk_score": 0.64,
  "band": "high",
  "confidence": 0.8,
  "data_gaps": ["No supplier financial health data available"]
}
```
