#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook (async) — register session early."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekal.config import load_config
from rekal.core import RekalStore

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
    cwd = hook_input.get("cwd", "")

    if not session_id:
        return

    store = RekalStore(config)
    try:
        store.ensure_session(session_id, source="claude", workspace_path=cwd)
    finally:
        store.close()


if __name__ == "__main__":
    main()
