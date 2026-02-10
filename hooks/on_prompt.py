#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook (async) — generate early session title."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekal.config import load_config
from rekal.core import RekalStore
from rekal.llm import generate_title

logging.basicConfig(
    filename=str(Path.home() / ".rekal" / "rekal.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("rekal")


def main():
    config = load_config()
    if not config.enabled:
        return

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        log.error("Failed to read hook input from stdin")
        return

    session_id = hook_input.get("session_id")
    prompt = hook_input.get("prompt", "")
    cwd = hook_input.get("cwd", "")

    if not session_id or not prompt:
        return

    store = RekalStore(config)
    try:
        # Check if this session already has a title (not the first prompt)
        existing = store.conn.execute(
            "SELECT title FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if existing and existing["title"]:
            return  # Already has a title, skip

        # Create session and generate early title
        store.ensure_session(session_id, source="claude", workspace_path=cwd)
        title = generate_title(prompt, config)
        store.conn.execute(
            "UPDATE sessions SET title = ? WHERE session_id = ?",
            (title, session_id),
        )
        store.conn.commit()
        log.info("Early title for %s: %s", session_id[:8], title)
    finally:
        store.close()


if __name__ == "__main__":
    main()
