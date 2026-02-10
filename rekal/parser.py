"""Transcript JSONL parser for Claude Code and Codex sessions."""

import json
from pathlib import Path

# Tool calls to skip (bulk data, not useful for summaries)
SKIP_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch"}


def parse_transcript(transcript_path: str | Path) -> dict:
    """Parse a Claude Code transcript JSONL file.

    Returns:
        {
            "prompts": str,
            "responses": str,
            "edits": str,
            "turn_count": int,
        }
    """
    path = Path(transcript_path)
    if not path.exists():
        return {"prompts": "", "responses": "",
                "edits": "", "turn_count": 0}

    user_parts = []
    output_parts = []
    code_parts = []
    turn_count = 0

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = entry.get("type", "")
            message = entry.get("message", {})

            if msg_type == "user":
                content = message.get("content", "")
                if isinstance(content, str):
                    if content:
                        user_parts.append(content)
                        turn_count += 1
                elif isinstance(content, list):
                    texts = [b["text"] for b in content
                             if isinstance(b, dict) and b.get("type") == "text"]
                    if texts:
                        user_parts.append(" ".join(texts))
                        turn_count += 1

            elif msg_type == "assistant":
                content = message.get("content", [])
                if isinstance(content, str):
                    output_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                output_parts.append(block["text"])
                            elif block.get("type") == "tool_use":
                                tool_name = block.get("name", "")
                                if tool_name in SKIP_TOOLS:
                                    continue
                                if tool_name in ("Write", "Edit"):
                                    inp = block.get("input", {})
                                    path_str = inp.get("file_path", "")
                                    if path_str:
                                        code_parts.append(f"[{tool_name}: {path_str}]")

    return {
        "prompts": "\n\n".join(user_parts),
        "responses": "\n\n".join(output_parts),
        "edits": "\n".join(code_parts),
        "turn_count": turn_count,
    }


def extract_latest_turn(transcript_path: str | Path) -> dict:
    """Extract only the latest turn pair from a transcript.

    Walks backwards from the end to find the last user message
    and all agent output after it.
    """
    path = Path(transcript_path)
    if not path.exists():
        return {"prompt": "", "response": "",
                "edits": "", "turn_number": 0}

    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not entries:
        return {"prompt": "", "response": "",
                "edits": "", "turn_number": 0}

    # Count user turns and find the last one
    user_turn_count = 0
    last_user_idx = -1
    for i, entry in enumerate(entries):
        if entry.get("type") == "user":
            content = entry.get("message", {}).get("content", "")
            # Skip tool_result entries (not real user messages)
            if isinstance(content, str) and content:
                user_turn_count += 1
                last_user_idx = i
            elif isinstance(content, list):
                has_text = any(
                    isinstance(b, dict) and b.get("type") == "text"
                    for b in content
                )
                if has_text:
                    user_turn_count += 1
                    last_user_idx = i

    if last_user_idx < 0:
        return {"prompt": "", "response": "",
                "edits": "", "turn_number": 0}

    # Extract user message
    user_entry = entries[last_user_idx]
    user_content = user_entry.get("message", {}).get("content", "")
    if isinstance(user_content, list):
        user_content = " ".join(
            b["text"] for b in user_content
            if isinstance(b, dict) and b.get("type") == "text"
        )

    # Extract agent output after the last user message
    output_parts = []
    code_parts = []
    for entry in entries[last_user_idx + 1:]:
        if entry.get("type") != "assistant":
            continue
        content = entry.get("message", {}).get("content", [])
        if isinstance(content, str):
            output_parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        output_parts.append(block["text"])
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "")
                        if tool_name in SKIP_TOOLS:
                            continue
                        if tool_name in ("Write", "Edit"):
                            inp = block.get("input", {})
                            p = inp.get("file_path", "")
                            if p:
                                code_parts.append(f"[{tool_name}: {p}]")

    return {
        "prompt": user_content,
        "response": "\n\n".join(output_parts),
        "edits": "\n".join(code_parts),
        "turn_number": user_turn_count,
    }
