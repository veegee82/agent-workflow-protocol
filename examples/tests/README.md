# Code Mode E2E Tests

End-to-end tests for the AWP delegation loop code_mode features.
Each test progressively increases complexity.

## Test Results (2026-03-27, gemini-2.0-flash via OpenRouter)

| Test | Description | Status | Duration | Key Validation |
|------|-------------|--------|----------|----------------|
| 01 | Basic code.execute | **PASSED** | 95s | Worker ran Python, saved JSON to `_output_dir` |
| 02 | Dynamic tool creation | **PASSED** | 175s | Worker created `dynamic.prime_check`, second worker tested it |
| 03 | File output (CSV+PNG) | **PASSED** | 127s | Worker saved sine_data.csv (3.8KB) + sine_chart.png (59KB) |
| 04 | Tool with secrets | PENDING | - | Tool accesses `_secrets`, returns masked key |
| 05 | Multi-iteration chain | PENDING | - | 3-phase pipeline: tool creation → data analysis → chart |

## Running

```bash
# Set API key
export $(grep -v '^#' ~/.awp/.env | grep '=' | xargs)
export LLM_MODEL="openrouter/google/gemini-2.0-flash-001"

# Run single test
python -m awp.cli run examples/tests/01-basic-code-execute \
  --task "Compute first 20 Fibonacci numbers and save as JSON" --debug

# Run all
./examples/tests/run_all_tests.sh
```

## What each test validates

### Test 01: Basic code.execute
- Worker uses `code.execute` tool to run Python in sandbox
- `_output_dir` variable is available and writable
- Files persist after execution

### Test 02: Dynamic tool creation
- Worker with `tool_creation: true` creates `dynamic.prime_check`
- Tool is registered in ToolRegistry
- Tool is persisted as JSON in `artifacts/tools/`
- Second worker can call the created tool
- Tool code is fully logged in debug output

### Test 03: File output (CSV + PNG chart)
- Worker uses `matplotlib.use("Agg")` for headless rendering
- CSV saved via `open()` builtin (no `os` import needed)
- PNG saved via `plt.savefig()` to `_output_dir`
- Both files verified on disk

### Test 04: Tool with secrets
- `secrets.yaml` provides `TEST_API_KEY`
- Worker creates tool with `required_secrets: ["TEST_API_KEY"]`
- Tool code accesses `_secrets.get("TEST_API_KEY")`
- Validates secret injection works (key length + masked output)

### Test 05: Multi-iteration chain
- Iteration 1: Create `dynamic.generate_dataset` tool
- Iteration 2: Use tool + analyze data → `analysis.json`
- Iteration 3: Read analysis → create chart → `revenue_chart.png`
- Tests tool chaining, file I/O, and multi-phase orchestration

## Notes

- Tests 04-05 require a capable LLM that reliably generates tool specs in JSON
- Free-tier models may fail on complex tool_creation prompts
- All tests use `dynamic_tools.enabled: true` and `persist: true`
- `shell.execute` is never used — `code.execute` is the correct tool
