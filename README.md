# Rekal

Local memory for AI coding sessions. Automatically indexes what you do in Claude Code and Codex, then lets you search it later.

## What it does

- **Indexes automatically** — hooks capture every turn as you work, summarizing with your local CLI
- **Searchable** — full-text search with BM25 scoring, recency decay, and workspace affinity
- **Cross-platform** — works with both Claude Code and OpenAI Codex
- **Local-only** — everything stays in a SQLite database on your machine
- **Zero API keys** — uses your existing `claude` or `codex` CLI for summarization

## Install

```bash
git clone <repo-url> && cd rekal
python3 install.py
```

This will:
1. Create `~/.rekal/` with config and database
2. Add async hooks to Claude Code and/or Codex
3. Install the `/rekal` skill for both platforms

## Usage

From any Claude Code or Codex session:

```
/rekal auth middleware          # search past sessions
/rekal --recent                 # list recent sessions
/rekal --session <id>           # view a specific session
/rekal --workspace crustland    # filter by project
```

Results are scored by keyword relevance, recency, and whether you're in the same project.

## How it works

```
You code normally
    |
    v
Hooks fire on each turn (async, non-blocking)
    |
    v
Transcript parsed → LLM generates title, summary, semantic tags
    |
    v
Stored in local SQLite with FTS5 index
    |
    v
/rekal queries the index and returns ranked results
```

**Hooks:**
| Event | Claude Code | Codex |
|-------|-------------|-------|
| Turn complete | `Stop` hook | `notify` hook |
| Session end | `SessionEnd` hook | — |
| New prompt | `UserPromptSubmit` hook | — |

## Configure

Edit `~/.rekal/config.yaml`:

```yaml
provider: claude        # or "codex"
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
