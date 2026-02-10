#!/usr/bin/env python3
"""Codex notify hook — capture turn on agent-turn-complete."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekal.config import load_config
from rekal.core import RekalStore
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

    # Codex passes JSON via stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        log.error("Failed to read Codex hook input")
        return

    event_type = hook_input.get("type", "")
    if event_type != "agent-turn-complete":
        return

    thread_id = hook_input.get("thread-id", "")
    cwd = hook_input.get("cwd", "")

    if not thread_id:
        log.warning("Missing thread-id in Codex hook input")
        return

    # Extract messages
    input_messages = hook_input.get("input-messages", [])
    last_output = hook_input.get("last-assistant-message", "")

    user_message = ""
    if isinstance(input_messages, list):
        for msg in reversed(input_messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    user_message = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                break

    if not user_message and not last_output:
        return

    agent_reply = ""
    if isinstance(last_output, str):
        agent_reply = last_output
    elif isinstance(last_output, dict):
        content = last_output.get("content", "")
        if isinstance(content, str):
            agent_reply = content
        elif isinstance(content, list):
            agent_reply = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )

    # Generate summary
    result = summarize_turn(user_message, agent_reply, "", config)

    # Store
    store = RekalStore(config)
    try:
        session_id = f"codex-{thread_id}"
        store.ensure_session(session_id, source="codex", workspace_path=cwd)

        # Get current turn count for this session
        row = store.conn.execute(
            "SELECT COALESCE(MAX(turn_number), 0) as max_turn FROM turns WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        turn_number = (row["max_turn"] if row else 0) + 1

        store.store_turn(
            session_id=session_id,
            turn_number=turn_number,
            user_message=user_message[:config.max_prompt_chars],
            agent_output=agent_reply[:config.max_response_chars],
            title=result.get("title", ""),
            description=result.get("description", ""),
            tags=result.get("tags", ""),
            model_name=config.model,
        )
        log.info("Codex turn %d for thread %s: %s",
                 turn_number, thread_id[:8], result.get("title", ""))
    finally:
        store.close()


if __name__ == "__main__":
    main()
