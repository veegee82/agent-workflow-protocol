# Contributing to AWP

Thank you for your interest in contributing to the Agent Workflow Protocol. This document explains how to propose changes, the standards we follow, and the review process.

## How to Propose Changes

### 1. Open an Issue

All changes start with a GitHub issue. Describe the problem or enhancement clearly. For non-trivial changes, the issue serves as a lightweight RFC (Request for Comments) where the community can discuss the proposal before implementation begins.

Issue types:

- **Bug report** -- Something in the specification is unclear, contradictory, or incorrect
- **Feature request** -- A new capability, layer extension, or validation rule
- **Clarification** -- A section of the spec needs better explanation or examples
- **Tooling** -- Improvements to the reference implementation, validator, or examples

### 2. Write an RFC (for significant changes)

For changes that affect the protocol semantics, layer model, compliance levels, or validation rules, write a short RFC in the issue body:

- **Problem** -- What is the current limitation or gap?
- **Proposal** -- What change do you propose?
- **Rationale** -- Why is this the right approach?
- **Alternatives** -- What other approaches were considered?
- **Impact** -- Which layers, compliance levels, or validation rules are affected?

### 3. Submit a Pull Request

Once the issue has been discussed and the approach is agreed upon:

1. Fork the repository
2. Create a branch: `feature/<short-description>` or `fix/<short-description>`
3. Make your changes
4. Ensure all validation checks pass
5. Submit a pull request referencing the issue

## Code Style -- Reference Implementation

The reference implementation is written in Python. Follow these conventions:

- **Python 3.10+** -- Use modern syntax (type unions with `|`, `match` statements where appropriate)
- **Type annotations** -- All public functions must have type annotations
- **PEP 8** -- Enforced by `ruff check .`
- **Formatting** -- Enforced by `ruff format .`
- **Logging** -- Use the `logging` module, never `print()`
- **Data classes** -- Use `dataclasses` or `pydantic` for structured data
- **Naming** -- `snake_case` for functions and modules, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants

## Documentation Standards

### Specification Documents (`spec/`)

The specification uses RFC 2119 language:

- **MUST** / **MUST NOT** -- Absolute requirement or prohibition
- **SHOULD** / **SHOULD NOT** -- Recommended but not mandatory
- **MAY** -- Truly optional

All normative statements must use these keywords consistently. Non-normative text (examples, rationale) should avoid these keywords.

Each specification document should include:

1. A clear statement of purpose
2. Normative requirements using RFC 2119 keywords
3. A YAML or JSON schema definition where applicable
4. At least one example
5. A validation rules section listing checkable constraints

### Primer Documents (`primer/`)

Primer documents are non-normative. They explain concepts, provide tutorials, and give context. They should be:

- Written in plain, accessible English
- Free of jargon (or with jargon clearly defined on first use)
- Rich in examples
- Cross-referenced with relevant spec documents

### Examples (`examples/`)

Every example must:

- Be a valid AWP workflow that passes `awp validate`
- Include a README explaining what the example demonstrates
- Specify the minimum compliance level required
- Be self-contained (no external dependencies beyond an LLM API key)

## Review Process

### For Specification Changes

1. **Issue discussion** -- At least 7 days for community feedback
2. **RFC review** -- Maintainers review the RFC for completeness and compatibility
3. **Implementation** -- PR submitted with spec changes, updated examples, and updated validation rules
4. **Review** -- At least one maintainer approval required
5. **Merge** -- Squash merge to main

### For Non-Specification Changes

Documentation fixes, example additions, and tooling improvements follow a lighter process:

1. **PR submitted** -- Referencing an issue if one exists
2. **Review** -- At least one maintainer approval
3. **Merge** -- Squash merge to main

### For Breaking Changes

Changes that would break existing workflows or runtimes require:

1. A major version bump (e.g., 1.x to 2.0)
2. A migration guide
3. A deprecation period of at least one minor version where possible
4. Approval from at least two maintainers

## Commit Message Format

Use conventional commit prefixes:

- `feat:` -- New feature or capability
- `fix:` -- Bug fix in spec or implementation
- `docs:` -- Documentation changes
- `refactor:` -- Code restructuring without behavior change
- `test:` -- Test additions or modifications
- `chore:` -- Maintenance tasks (CI, dependencies, etc.)

Examples:

```
feat: add Layer 3 message envelope schema
fix: correct validation rule for circular dependencies
docs: clarify memory tier persistence semantics
```

## Questions?

Open an issue with the label `question` or start a discussion in the repository's Discussions tab.
