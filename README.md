<p align="center">
  <img src="banner.png" alt="Rekal" width="600">
</p>

<p align="center">Persistent memory that works across Claude Code and Codex.<br>One local database, both platforms, zero effort from your agents.</p>

---

## The problem

Claude Code and Codex sessions are isolated. When a session ends, everything the agent learned — bug fixes, architecture decisions, debugging paths — is gone. The next session starts from scratch. Agents waste turns rediscovering what was already solved.

## How Rekal fixes it

Rekal runs silently in the background. It captures every turn from both Claude Code and Codex into a **single shared SQLite database**. When an agent needs context from past work, `/rekal` searches across all sessions — regardless of which tool created them.

A bug fixed in Claude Code yesterday? Your Codex session today can find it. A refactor planned in Codex last week? Claude Code picks up right where it left off.

- **Unified memory** — Claude Code and Codex sessions stored together, searchable from either platform
- **Automatic** — async hooks capture turns as you work, no agent effort required
- **Ranked results** — full-text search scored by relevance, recency, and workspace affinity
- **Local-only** — everything stays on your machine in `~/.rekal/`
- **Zero API keys** — uses your existing `claude` or `codex` CLI for summarization

## Install

```bash
git clone https://github.com/RolandSherwin/rekal.git && cd rekal
python3 install.py
```

This will:
1. Create `~/.rekal/` with config and database
2. Add async hooks to Claude Code and/or Codex
3. Install the `/rekal` skill for both platforms

## Usage

From any Claude Code or Codex session:

```
/rekal auth middleware          # search across all past sessions
/rekal --recent                 # list recent sessions (both platforms)
/rekal --session <id>           # view a specific session
/rekal --workspace crustland    # filter by project
```

## How it works

```
You code in Claude Code or Codex
    |
    v
Hooks fire on each turn (async, non-blocking)
    |
    v
Transcript parsed → LLM generates title, summary, semantic tags
    |
    v
Stored in shared SQLite with FTS5 index
    |
    v
/rekal queries from either platform → ranked results
```

| Event | Claude Code | Codex |
|-------|-------------|-------|
| Turn complete | `Stop` hook | `notify` hook |
| Session end | `SessionEnd` hook | — |
| New prompt | `UserPromptSubmit` hook | — |

## Configure

Edit `~/.rekal/config.yaml`:

```yaml
provider: claude        # or "codex" — which CLI to use for summarization
model: haiku            # cheapest model, used for summaries
enabled: true
timeout: 30
```

## Uninstall

```bash
python3 uninstall.py
```

Removes hooks and skills. Your data stays at `~/.rekal/` unless you delete it manually.

## Requirements

- Python 3.10+
- Claude Code (`claude` CLI) and/or Codex (`codex` CLI)
- No additional Python packages required
