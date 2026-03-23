# AWP Python Reference Implementation

Python reference tooling for the Agent Workflow Protocol (AWP). Provides parsing,
validation, packaging, and visualization of AWP workflow definitions.

## Install

```bash
pip install -e .
```

## CLI Usage

```bash
# Validate a workflow
awp validate path/to/workflow/

# Check compliance level
awp compliance path/to/workflow/ --level L3

# Pack a workflow into a .awp.zip archive
awp pack path/to/workflow/ -o my-workflow.awp.zip

# Unpack an archive
awp unpack my-workflow.awp.zip -o output/

# Visualize the DAG
awp visualize path/to/workflow/ --format mermaid

# Generate an agent identity card
awp identity-card path/to/agent.awp.yaml
```

## Package Structure

```
src/awp/
  __init__.py          # Package root
  cli.py               # CLI entry point
  visualizer.py        # Mermaid / ASCII DAG rendering
  schema_generator.py  # output_schema.json generation from contracts
  models/              # Pydantic data models (manifest, agent, orchestration, etc.)
  parser/              # YAML parsers for workflow.awp.yaml and agent.awp.yaml
  validator/           # Schema, graph, contract, compliance, and rule validators
  packager/            # Pack/unpack workflows as .awp.zip archives
```

## Library Usage

```python
from awp.parser import parse_manifest, parse_agent
from awp.validator import validate_graph, validate_contracts, check_compliance

manifest = parse_manifest("workflow.awp.yaml")
agent = parse_agent("agents/researcher/agent.awp.yaml")
```
