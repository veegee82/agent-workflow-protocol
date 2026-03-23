# AWP Conformance Test Suite

This directory contains the conformance test suite for Agent Workflow Protocol
implementations. It provides a set of valid and invalid fixture files that any
AWP-compliant parser and validator must handle correctly.

## Structure

- `suite.json` -- Top-level manifest listing all test fixtures and expected outcomes.
- `fixtures/valid/` -- Workflow definitions that must parse and validate without errors.
- `fixtures/invalid/` -- Workflow definitions that must produce specific validation errors.

## Usage

An AWP implementation should:

1. Parse each fixture in `fixtures/valid/` and confirm it passes validation at the
   expected compliance level.
2. Parse each fixture in `fixtures/invalid/` and confirm it produces the expected
   error (or fails to parse).

## Adding Fixtures

Each fixture is a standalone `workflow.awp.yaml` (or fragment) that exercises a
specific rule or compliance level. Reference it in `suite.json` with the expected
outcome.
