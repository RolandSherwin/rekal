#!/usr/bin/env python3
"""Claude Code Stop hook (async) — summarize the latest turn."""

import json
import logging
import sys
from pathlib import Path

# Add parent dir so we can import rekal package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekal.config import load_config
from rekal.core import RekalStore
from rekal.parser import extract_latest_turn
from rekal.llm import summarize_turn

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

    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        log.error("Failed to read hook input from stdin")
        return

    session_id = hook_input.get("session_id")
    transcript_path = hook_input.get("transcript_path")
    cwd = hook_input.get("cwd", "")

    if not session_id or not transcript_path:
        log.warning("Missing session_id or transcript_path in hook input")
        return

    # Skip if this is a hook-triggered stop (avoid infinite loops)
    if hook_input.get("stop_hook_active"):
        return

    # Parse the latest turn from the transcript
    turn = extract_latest_turn(transcript_path)
    if not turn["prompt"]:
        log.info("No user prompt found in latest turn, skipping")
        return

    # Generate summary + tags via LLM
    result = summarize_turn(
        turn["prompt"],
        turn["response"],
        turn["edits"],
        config,
    )

    # Store in SQLite
    store = RekalStore(config)
    try:
        store.ensure_session(session_id, source="claude", workspace_path=cwd)
        store.store_turn(
            session_id=session_id,
            turn_number=turn["turn_number"],
            user_message=turn["prompt"][:config.max_prompt_chars],
            agent_output=turn["response"][:config.max_response_chars],
            title=result.get("title", ""),
            description=result.get("description", ""),
            tags=result.get("tags", ""),
            model_name=config.model,
        )
        log.info("Stored turn %d for session %s: %s",
                 turn["turn_number"], session_id[:8], result.get("title", ""))
    finally:
        store.close()


if __name__ == "__main__":
    main()
