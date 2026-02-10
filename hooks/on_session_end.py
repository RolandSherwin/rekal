#!/usr/bin/env python3
"""Claude Code SessionEnd hook (async) — generate session summary."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekal.config import load_config
from rekal.core import RekalStore
from rekal.llm import summarize_session

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
    if not session_id:
        log.warning("Missing session_id in SessionEnd hook input")
        return

    store = RekalStore(config)
    try:
        turns = store.get_session_turns(session_id)
        if not turns:
            log.info("No turns found for session %s, skipping summary", session_id[:8])
            return

        result = summarize_session(turns, config)
        store.update_session_summary(
            session_id,
            title=result.get("session_title", ""),
            summary=result.get("session_summary", ""),
        )
        log.info("Session summary for %s: %s", session_id[:8],
                 result.get("session_title", ""))
    finally:
        store.close()


if __name__ == "__main__":
    main()
