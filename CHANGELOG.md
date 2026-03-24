# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-03-23

### Added

- Initial AWP 1.0.0 specification
- 7-layer protocol model (Manifest, Agent Identity, Capabilities, Communication, Memory & State, Orchestration, Observability)
- Compliance levels L0-L5 (Core, Composable, Communicative, Memorable, Observable, Enterprise)
- 24 validation rules (R1-R24) for pre-execution checking
- Python reference implementation
- Build skill for AI assistants
- 6 example workflows (hello-world, research-pipeline, chat-team, memory-workflow, observable-analytics, enterprise)
- Code Mode: agents write code against a typed SDK instead of calling tools one-by-one
- Custom MCP tools with secret injection
- Cloudflare Workers adapter for edge deployment
- Primer documentation (motivation, concepts, quickstart, comparison, FAQ)
- Normative specification documents for all 7 layers
- `.awp.zip` packaging format
- MCP-compatible tool integration at Layer 2
- Message bus protocol at Layer 3
- 4-tier memory model (working, short-term, long-term, shared)
- OpenTelemetry-compatible observability at Layer 6
- SemVer versioning for manifests and protocol
