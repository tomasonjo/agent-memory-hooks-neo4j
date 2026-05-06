#!/bin/bash
# Wrapper invoked by Codex. Pipes stdin (hook JSON) to the shared logger.
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
exec "$PYTHON" "$REPO_ROOT/hooks/log_event.py" --client codex
