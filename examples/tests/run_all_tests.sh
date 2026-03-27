#!/bin/bash
# E2E Code Mode Tests — runs all 5 tests sequentially
# Usage: ./run_all_tests.sh [test_number]
#   ./run_all_tests.sh        # Run all
#   ./run_all_tests.sh 1      # Run only test 1

set -euo pipefail
cd "$(dirname "$0")"

# Load AWP env
source ~/.awp/.env 2>/dev/null || true
export LLM_MODEL="${LLM_MODEL:-openrouter/nvidia/nemotron-3-super-120b-a12b:free}"

TESTS=(
  "01-basic-code-execute"
  "02-dynamic-tool-creation"
  "03-file-output-chart"
  "04-tool-with-secrets"
  "05-multi-iteration-chain"
)

run_test() {
  local test_dir="$1"
  local test_name=$(basename "$test_dir")
  echo ""
  echo "================================================================"
  echo "  TEST: $test_name"
  echo "  Model: $LLM_MODEL"
  echo "================================================================"
  echo ""

  # Clean previous run
  rm -rf "$test_dir/workspace/runs" "$test_dir/output/"*

  # Run
  cd "$(git rev-parse --show-toplevel)"
  if python -m awp.cli run "$test_dir" --task "Execute the test task" --debug 2>&1 | tee "$test_dir/output/run.log"; then
    echo ""
    echo "  RESULT: PASSED"
  else
    echo ""
    echo "  RESULT: FAILED (exit code $?)"
  fi

  # Show generated files
  echo ""
  echo "  Generated files:"
  find "$test_dir/output" "$test_dir/workspace" -type f 2>/dev/null | head -30
  echo "================================================================"
  echo ""
}

if [ "${1:-}" != "" ]; then
  idx=$((${1} - 1))
  run_test "${TESTS[$idx]}"
else
  for t in "${TESTS[@]}"; do
    run_test "$t"
  done
fi
