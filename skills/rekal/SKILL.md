---
name: rekal
description: >-
  Search past AI coding sessions stored locally. Use when the user says
  "search history", "what did I do", "recall", "rekal", "past sessions",
  or wants to find previous work, avoid repeating solutions, or continue
  where a previous session left off.
argument-hint: "[query | --recent | --session <id> | --stats]"
---

Run the Rekal search tool with the user's query:

```bash
PYTHONPATH="$REKAL_REPO" python3 -m rekal.search $ARGUMENTS
```

## Search modes

- `/rekal <query>` — Full-text search. Results scored by relevance, recency, and workspace affinity.
- `/rekal --recent` or `/rekal --recent 20` — Show N most recent sessions (default 10).
- `/rekal --session <id>` — Show all turns for a session. Use the session ID from search results (prefix or full).
- `/rekal --workspace <path>` — Filter results to a specific project.
- `/rekal --stats` — Show usage statistics (sessions, turns indexed, search hit rate).
- Flags combine: `/rekal auth --workspace crustland --limit 5`

## How to use results

- Results include titles, summaries, semantic tags, and timestamps.
- Use this context to avoid repeating past work or recall how a problem was solved.
- If results aren't specific enough, try different keywords — the index includes LLM-generated semantic tags beyond the literal text.
