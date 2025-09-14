#!/usr/bin/env bash
set -euo pipefail

# SAM test runner: runs test groups with safe defaults to avoid hangs.

export SAM_TEST_MODE=${SAM_TEST_MODE:-1}
export PYTHONASYNCIODEBUG=${PYTHONASYNCIODEBUG:-0}

# Ensure a writable temp directory to avoid OS sandbox surprises
export TMPDIR=${TMPDIR:-"$(pwd)/.sam/tmp"}
mkdir -p "$TMPDIR"
export UV_CACHE_DIR=${UV_CACHE_DIR:-"$(pwd)/.sam/uv-cache"}
mkdir -p "$UV_CACHE_DIR"

echo "Running tests with SAM_TEST_MODE=$SAM_TEST_MODE TMPDIR=$TMPDIR UV_CACHE_DIR=$UV_CACHE_DIR"

run() {
  echo "\n==> $*\n"
  uv run pytest -q "$@"
}

# 1) Utils and error handling (fast)
run tests/test_utils_* tests/test_error_* tests/test_validators.py tests/test_rate_limiter.py

# 2) DB / connection pool / memory
run tests/test_connection_pool.py
run tests/test_memory.py tests/test_memory_list_sessions.py tests/test_memory_clear_all_sessions.py tests/test_memory_session_defaults.py

# 3) Integrations and tools
run tests/test_integrations.py tests/test_smart_trader.py tests/test_tool_calls.py tests/test_tools.py

# 4) Agent, CLI (non-interactive tests only)
run tests/test_agent.py tests/test_cli.py tests/test_commands_health.py tests/test_commands_onboard.py

echo "\nAll test groups completed."
