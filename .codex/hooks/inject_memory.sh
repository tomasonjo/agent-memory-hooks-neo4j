#!/bin/bash
# Wrapper invoked by Codex for the memory injector.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
exec "$PYTHON" "$REPO_ROOT/hooks/inject_memory.py" --client codex
