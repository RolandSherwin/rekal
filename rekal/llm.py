"""LLM caller using local Claude Code or Codex CLI — no API keys needed."""

import json
import logging
import subprocess

from .config import RekalConfig

log = logging.getLogger("rekal")

TURN_SUMMARY_PROMPT = """\
Index one coding turn for future search retrieval.

Return ONLY this JSON (no markdown, no explanation):
{"title": "...", "description": "...", "tags": ["..."]}

title: Outcome headline, max 80 chars. Be specific.
  YES: "Fix null pointer in JWT refresh flow"
  YES: "Add FTS5 index to turns table"
  NO:  "Update code" / "Work on auth improvements"

description: 2-5 bullet points with file paths, function names, errors, or decisions that would help a future agent judge relevance.

tags: 5-10 search terms across four dimensions:
  domain (auth, payments, rendering, deployment)
  action (debug, implement, refactor, configure, test)
  stack  (react, golang, postgres, redis, docker)
  detail (jwt-refresh, rate-limiter, fts5-index)
  SKIP generic words: code, fix, update, change, work, file."""


SESSION_RECAP_PROMPT = """\
Summarize a completed coding session for future recall.

Return ONLY this JSON (no markdown, no explanation):
{"session_title": "...", "session_summary": "..."}

session_title: Overall goal or theme, max 80 chars.
session_summary: 2-4 sentences covering outcomes, key decisions, and unresolved issues. Focus on what was accomplished, not a turn-by-turn retelling."""


QUICK_TITLE_PROMPT = """\
Write a short title (max 60 chars) describing the intent of this coding session.

Return ONLY this JSON: {"title": "..."}"""


def _call_claude(system: str, user: str, config: RekalConfig) -> dict:
    cmd = [
        "claude", "-p",
        "--model", config.model,
        "--tools", "",
        "--output-format", "json",
        "--no-session-persistence",
        "--system-prompt", system,
        user,
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.timeout,
    )

    if result.returncode != 0:
        log.error("claude CLI failed (exit %d): %s", result.returncode, result.stderr)
        raise RuntimeError(f"claude CLI failed: {result.stderr[:200]}")

    data = json.loads(result.stdout)
    # --output-format json wraps in {"type":"result","result":"..."}
    text = data.get("result", result.stdout)
    if isinstance(text, str):
        return json.loads(text)
    return text


def _call_codex(system: str, user: str, config: RekalConfig) -> dict:
    prompt = f"{system}\n\n{user}"
    cmd = [
        "codex", "exec",
        "--model", config.model,
        "--json",
        prompt,
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.timeout,
    )

    if result.returncode != 0:
        log.error("codex CLI failed (exit %d): %s", result.returncode, result.stderr)
        raise RuntimeError(f"codex CLI failed: {result.stderr[:200]}")

    # Codex --json outputs JSONL events, last message has the result
    last_text = ""
    for line in result.stdout.strip().splitlines():
        try:
            event = json.loads(line)
            # Look for agent output in response events
            if event.get("type") == "message" and event.get("role") == "assistant":
                content = event.get("content", "")
                if isinstance(content, str):
                    last_text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_text = block["text"]
        except json.JSONDecodeError:
            continue

    if not last_text:
        # Fallback: try parsing entire stdout as plain text
        last_text = result.stdout.strip()

    return json.loads(last_text)


def call_llm(system: str, user: str, config: RekalConfig) -> dict:
    if config.provider == "codex":
        return _call_codex(system, user, config)
    return _call_claude(system, user, config)


def summarize_turn(prompt: str, response: str,
                   edits: str, config: RekalConfig) -> dict:
    """Generate title + description + tags for a single turn."""
    user_input = f"""USER ASKED:
{prompt[:config.max_prompt_chars]}

AGENT OUTPUT:
{response[:config.max_response_chars]}

FILES CHANGED:
{edits[:config.max_edit_chars] if edits.strip() else "(none)"}"""

    try:
        result = call_llm(TURN_SUMMARY_PROMPT, user_input, config)
    except Exception as e:
        log.error("LLM summarization failed: %s", e)
        return {
            "title": prompt[:60] if prompt else "Untitled turn",
            "description": "- Summarization failed",
            "tags": [],
        }

    # Normalize tags to comma-separated string
    tags = result.get("tags", [])
    if isinstance(tags, list):
        result["tags"] = ", ".join(str(t) for t in tags)

    return result


def summarize_session(turns: list[dict], config: RekalConfig) -> dict:
    """Generate session title + summary from turn data."""
    turns_text = "\n\n".join(
        f"Turn {i+1}: {t.get('title', 'Untitled')}\n{t.get('description', '')}"
        for i, t in enumerate(turns)
    )

    user_input = f"SESSION TURNS:\n\n{turns_text}"

    try:
        return call_llm(SESSION_RECAP_PROMPT, user_input, config)
    except Exception as e:
        log.error("Session recap failed: %s", e)
        return {
            "session_title": turns[0].get("title", "Untitled session") if turns else "Untitled",
            "session_summary": f"Session with {len(turns)} turns.",
        }


def generate_title(opening_prompt: str, config: RekalConfig) -> str:
    """Generate a session title from the first user prompt."""
    try:
        result = call_llm(
            QUICK_TITLE_PROMPT,
            opening_prompt[:500],
            config,
        )
        return result.get("title", opening_prompt[:60])
    except Exception as e:
        log.error("Title generation failed: %s", e)
        return opening_prompt[:60]
