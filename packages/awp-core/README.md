# awp-core

**Agent Workflow Protocol -- Core Library**

Models, parser, validator, and CLI tools for the [AWP specification](https://github.com/veegee82/agent-workflow-protocol).

## Installation

```bash
pip install awp-core
```

## What's included

- **Models** (`awp.models`) -- Pydantic models for all 7 AWP layers (manifest, identity, capabilities, communication, memory, orchestration, observability)
- **Parser** (`awp.parser`) -- Parse `workflow.awp.yaml` and `agent.awp.yaml` into typed models
- **Validator** (`awp.validator`) -- Rule engine (R1-R30) covering naming, graph structure, confidence, tool namespaces, budgets
- **Visualizer** (`awp.visualizer`) -- Render workflow DAGs as Mermaid diagrams
- **Packager** (`awp.packager`) -- Pack/unpack workflows as `.awp.zip` archives
- **CLI** -- `awp validate`, `awp compliance`, `awp visualize`, `awp pack`

## Usage

```python
from awp.models import AWPManifest
from awp.parser import parse_manifest
from awp.validator import validate_rules
```

## Need to run workflows?

Install [awp-runtime](https://pypi.org/project/awp-runtime/) for the execution engines:

```bash
pip install awp-runtime
```

## License

MIT -- see [LICENSE](https://github.com/veegee82/agent-workflow-protocol/blob/main/LICENSE).
