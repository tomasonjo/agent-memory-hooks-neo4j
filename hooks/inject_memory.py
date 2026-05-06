#!/usr/bin/env python3
"""
Shared hook: inject :Memory nodes into the session as additional context.

- SessionStart: load every `profile/*` memory in full + a TOC of remaining paths
  so the model knows what else is available.
- UserPromptSubmit: rough keyword match between the prompt and memory bodies/paths;
  inject the top hits inline.

Used by both Claude Code and Codex. Both clients accept the same output shape:
  {"hookSpecificOutput": {"hookEventName": "...", "additionalContext": "..."}}
"""

import argparse
import json
import os
import re
import sys

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("HOOKS_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("HOOKS_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("HOOKS_NEO4J_PASSWORD", "password")

MAX_PROMPT_HITS = 5
MIN_KEYWORD_LEN = 4

STOPWORDS = {
    "this", "that", "with", "from", "have", "what", "when", "where", "which",
    "would", "could", "should", "your", "their", "there", "about", "into",
    "they", "them", "then", "than", "some", "make", "like", "want", "need",
    "just", "only", "also", "still", "very", "much", "more", "most", "ours",
    "please", "thanks", "code", "file", "files",
}


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def session_start_context() -> str:
    with get_driver() as driver, driver.session() as s:
        profile = list(s.run(
            "MATCH (m:Memory) WHERE m.path STARTS WITH 'profile/' "
            "RETURN m.path AS path, m.content AS content ORDER BY m.path"
        ))
        other = list(s.run(
            "MATCH (m:Memory) WHERE NOT m.path STARTS WITH 'profile/' "
            "RETURN m.path AS path ORDER BY m.path"
        ))

    if not profile and not other:
        return ""

    parts = ["# Memory (from prior sessions)\n"]
    if profile:
        parts.append("## Profile\n")
        for r in profile:
            parts.append(f"### {r['path']}\n{r['content']}\n")
    if other:
        parts.append("## Other available memories\n")
        parts.append("Other memory paths exist but were not auto-loaded. "
                     "Recall as needed:\n")
        for r in other:
            parts.append(f"- `{r['path']}`")
    return "\n".join(parts)


def keywords(prompt: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", prompt.lower())
    return [w for w in words if len(w) >= MIN_KEYWORD_LEN and w not in STOPWORDS]


def prompt_context(prompt: str) -> str:
    kws = keywords(prompt)
    if not kws:
        return ""

    cypher = """
    MATCH (m:Memory)
    WITH m, [k IN $keywords WHERE
        toLower(m.content) CONTAINS k OR toLower(m.path) CONTAINS k
    ] AS hits
    WHERE size(hits) > 0
    RETURN m.path AS path, m.content AS content, size(hits) AS score
    ORDER BY score DESC, m.path
    LIMIT $limit
    """
    with get_driver() as driver, driver.session() as s:
        rows = list(s.run(cypher, keywords=kws, limit=MAX_PROMPT_HITS))

    rows = [r for r in rows if not r["path"].startswith("profile/")]
    if not rows:
        return ""

    parts = ["# Relevant memory for this prompt\n"]
    for r in rows:
        parts.append(f"## {r['path']}\n{r['content']}\n")
    return "\n".join(parts)


def emit(event_name: str, context: str):
    if not context.strip():
        return
    out = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }
    print(json.dumps(out))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True, choices=["claude_code", "codex", "cursor"])
    parser.parse_args()

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
        event = data.get("hook_event_name")
        normalized = (event or "").lower()
        if normalized in {"sessionstart", "session_start"}:
            emit(event or "sessionStart", session_start_context())
        elif normalized in {"userpromptsubmit", "beforesubmitprompt"}:
            emit(event or "beforeSubmitPrompt", prompt_context(data.get("prompt", "")))
    except Exception as e:
        print(f"inject_memory error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
