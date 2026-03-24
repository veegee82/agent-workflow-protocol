# AWP Example Workflows

Complete example workflows covering all AWP compliance levels and features.

## Examples

| Example | Level | Features Demonstrated |
|---------|-------|----------------------|
| [01-hello-world](01-hello-world/) | L0 Core | Single agent, basic orchestration, output contract |
| [02-research-pipeline](02-research-pipeline/) | L1 Composable | Multi-agent DAG, state sharing, web search tools |
| [03-chat-team](03-chat-team/) | L2 Communicative | Message bus, agent communication, channels |
| [04-memory-workflow](04-memory-workflow/) | L3 Memorable | Long-term memory, daily logs, memory tools |
| [05-observable-analytics](05-observable-analytics/) | L4 Observable | Tracing, metrics, audit trail, code execution |
| [06-enterprise](06-enterprise/) | L5 Enterprise | All features: security, skills, MCPs, code mode, conditional execution |

## Feature Coverage Matrix

| Feature | L0 | L1 | L2 | L3 | L4 | L5 |
|---------|----|----|----|----|----|----|
| Agent DAG | x | x | x | x | x | x |
| State Sharing | | x | x | x | x | x |
| Tool Calling (MCP) | | x | x | x | x | x |
| Message Bus | | | x | | | x |
| Agent Communication | | | x | | | x |
| Long-term Memory | | | | x | x | x |
| Daily Logs | | | | x | x | x |
| Memory Tools | | | | x | x | x |
| Observability/Tracing | | | | | x | x |
| Metrics Collection | | | | | x | x |
| Audit Trail | | | | | x | x |
| Code Execution | | | | | x | x |
| Security/ACL | | | | | | x |
| Circuit Breaker | | | | | | x |
| Rate Limiting | | | | | | x |
| Custom MCP Tools | | | | | | x |
| Skills Injection | | | | | | x |
| Conditional Execution | | | | | | x |
| Code Mode | | | | | | x |

## Running Examples

```bash
# Set your LLM API key
export LLM_API_KEY="your-openrouter-key"
export LLM_MODEL="anthropic/claude-sonnet-4"

# Run a specific example
cd reference/python
python -m awp run ../../examples/01-hello-world --task "Greet Alice"

# Run E2E tests (requires LLM_API_KEY)
pytest tests/test_examples_e2e.py -v --tb=short

# Run validation-only tests (no LLM needed)
pytest tests/test_e2e.py -v
```

## Compliance Levels

- **L0 Core**: Valid manifest + single agent + output contract
- **L1 Composable**: Multi-agent DAG + state sharing
- **L2 Communicative**: Message bus + channels
- **L3 Memorable**: 2+ memory tiers (long-term + daily)
- **L4 Observable**: Tracing + metrics + audit
- **L5 Enterprise**: All features + security (circuit breaker, ACL, rate limiting)
