#!/bin/bash
# Wrapper invoked by Cursor for the memory injector.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
exec "$PYTHON_BIN" "$REPO_ROOT/hooks/inject_memory.py" --client cursor
