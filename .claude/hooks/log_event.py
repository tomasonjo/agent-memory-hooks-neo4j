#!/usr/bin/env python3
"""
Claude Code hook script that logs events to Neo4j as a linked list per session.

Each session becomes a chain: (Session)-[:FIRST_EVENT]->(Event)-[:NEXT]->(Event)->...
The most recent event is also linked via (Session)-[:LATEST_EVENT]->(Event).
"""

import json
import sys
import os
from datetime import datetime, timezone

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("HOOKS_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("HOOKS_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("HOOKS_NEO4J_PASSWORD", "password")


MAX_RESPONSE_CHARS = 4000


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def _serialize_tool_response(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > MAX_RESPONSE_CHARS:
        text = text[:MAX_RESPONSE_CHARS] + f"...[truncated {len(text) - MAX_RESPONSE_CHARS} chars]"
    return text


def _read_transcript(path):
    if not path:
        return None
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return None


def ensure_constraints(tx):
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:Session) REQUIRE s.session_id IS UNIQUE")
    tx.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE")


def log_event(data: dict):
    session_id = data.get("session_id", "unknown")
    event_name = data.get("hook_event_name", "unknown")
    timestamp = datetime.now(timezone.utc).isoformat()

    event_id = f"{session_id}_{timestamp}_{event_name}"

    event_props = {
        "event_id": event_id,
        "event_name": event_name,
        "timestamp": timestamp,
        "cwd": data.get("cwd"),
        "tool_name": data.get("tool_name"),
        "tool_input": json.dumps(data.get("tool_input")) if data.get("tool_input") else None,
        "tool_response": _serialize_tool_response(data.get("tool_response"))
        if data.get("tool_response") is not None
        else None,
        "prompt": data.get("prompt"),
        "model": data.get("model"),
        "source": data.get("source"),
        "transcript_path": data.get("transcript_path"),
        "transcript": _read_transcript(data.get("transcript_path")),
    }
    event_props = {k: v for k, v in event_props.items() if v is not None}

    driver = get_driver()
    with driver.session() as session:
        session.execute_write(ensure_constraints)
        session.execute_write(_append_event, session_id, event_props)
    driver.close()


def _append_event(tx, session_id: str, event_props: dict):
    tx.run(
        """
        MERGE (s:Session {session_id: $session_id})
        ON CREATE SET s.created_at = $timestamp
        WITH s
        CREATE (e:Event $event_props)
        WITH s, e
        OPTIONAL MATCH (s)-[old_latest:LATEST_EVENT]->(prev:Event)
        DELETE old_latest
        WITH s, e, prev
        FOREACH (_ IN CASE WHEN prev IS NOT NULL THEN [1] ELSE [] END |
            CREATE (prev)-[:NEXT]->(e)
        )
        FOREACH (_ IN CASE WHEN prev IS NULL THEN [1] ELSE [] END |
            CREATE (s)-[:FIRST_EVENT]->(e)
        )
        CREATE (s)-[:LATEST_EVENT]->(e)
        """,
        session_id=session_id,
        timestamp=event_props.get("timestamp"),
        event_props=event_props,
    )


if __name__ == "__main__":
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        log_event(data)
    except Exception as e:
        print(f"Hook error: {e}", file=sys.stderr)
