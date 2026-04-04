---
name: {{SKILL_NAME}}
domain: {{DOMAIN}}
scope: {{project|agent}}
version: "1.0"
---

# {{SKILL_NAME}}

## Purpose

{{One sentence: what decision or task does this skill support?}}

## Concepts

{{Define the 3-7 key terms, frameworks, or models an agent needs to apply this skill.
Use definition-list style:}}

- **{{Term A}}**: {{definition}}
- **{{Term B}}**: {{definition}}
- **{{Term C}}**: {{definition}}

## Rules

{{Numbered, actionable constraints the agent MUST follow when applying this skill.
Each rule should be testable — an evaluator can check whether the output satisfies it.}}

1. {{RULE — e.g., "Always report risk as a normalized 0.0-1.0 score."}}
2. {{RULE — e.g., "Flag any assumption that lacks supporting data."}}
3. {{RULE — e.g., "Use ISO 8601 for all date fields."}}

## Procedure

{{Step-by-step sequence an agent should follow. Optional — omit if the skill is
purely declarative (reference knowledge only).}}

1. {{Step — e.g., "Extract relevant metrics from the input data."}}
2. {{Step — e.g., "Apply the scoring framework from Concepts."}}
3. {{Step — e.g., "Cross-validate against historical baselines."}}

## Examples

{{At least one concrete input → output pair showing correct skill application.
Use fenced blocks for structured data.}}

### Example 1: {{short label}}

**Input:**
```
{{example input}}
```

**Output:**
```
{{expected output}}
```

## References

{{Optional. Pointers to standards, papers, or external sources the skill draws from.
Omit this section if there are no external references.}}

- {{Reference — e.g., "NIST SP 800-53 Rev. 5 — Security and Privacy Controls"}}
