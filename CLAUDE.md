# Agent Memory Hooks (Claude Code + Codex + Cursor)

Hooks for Claude Code, Codex, and Cursor that store session events as a linked list in Neo4j.

## Setup

```bash
pip install -r requirements.txt
```

Set environment variables (or use defaults: bolt://localhost:7687, neo4j/password):
```bash
export HOOKS_NEO4J_URI=bolt://localhost:7687
export HOOKS_NEO4J_USER=neo4j
export HOOKS_NEO4J_PASSWORD=password
```

## Architecture

Each agent session creates a graph structure:

```
(Session {session_id, client}) -[:FIRST_EVENT]-> (Event {client}) -[:NEXT]-> (Event) -> ...
                               -[:LATEST_EVENT]-> (last Event)
```

Events captured: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop.
Codex additionally fires PermissionRequest (not currently registered).

`hooks/log_event.py` and `hooks/inject_memory.py` are shared. Per-client glue:
- `.claude/settings.json` → `.claude/hooks/*.sh` → `hooks/*.py --client claude_code`
- `.codex/hooks.json` → `.codex/hooks/*.sh` → `hooks/*.py --client codex`
- `.cursor/settings.json` → `.cursor/hooks/*.sh` → `hooks/*.py --client cursor`

## Testing

```bash
python test_hooks.py
```

Requires a running Neo4j instance.
