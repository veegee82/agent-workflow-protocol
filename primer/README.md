# AWP Primer -- Reading Guide

This primer introduces the Agent Workflow Protocol (AWP) from motivation through hands-on practice. Read the documents in order for the best experience.

## Recommended Reading Order

### 1. [motivation.md](motivation.md) -- Why AWP Exists

Start here. This document explains the fragmentation problem in multi-agent workflows, introduces AWP as the solution, and lays out the eight design principles that guide the specification. Read this to understand the *problem space*.

### 2. [concepts.md](concepts.md) -- Core Concepts

The conceptual foundation. Introduces the 7-layer model, explains what each layer does, shows the layer dependency graph, and presents the compliance levels (L0-L5). Includes a minimal YAML example to ground the abstraction. Read this to understand the *protocol structure*.

### 3. [quickstart.md](quickstart.md) -- Build Your First Workflow

A hands-on, step-by-step tutorial. In five minutes, you will create a complete AWP workflow with a manifest, agent configuration, system prompt, output schema, and Python implementation. Read this to understand the *developer experience*.

### 4. [comparison.md](comparison.md) -- AWP vs Existing Standards

A detailed comparison matrix covering AWP, MCP, A2A, OpenAPI, LangGraph, and CrewAI. Explains how AWP relates to and complements each standard. Read this to understand *where AWP fits* in the ecosystem.

### 5. [faq.md](faq.md) -- Frequently Asked Questions

Answers to common questions about compatibility, minimum requirements, memory, packaging, validation, and more.

## After the Primer

Once you have read the primer, continue with:

- **`spec/`** -- The normative specification. Uses RFC 2119 language (MUST, SHOULD, MAY). This is the authoritative reference for implementors.
- **`examples/`** -- Complete, runnable example workflows at various compliance levels.
- **`skill/`** -- The AWP build skill for AI assistants, enabling them to create new AWP workflows.
- **`reference/`** -- Reference implementation details and API documentation.
