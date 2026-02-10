"""CLI search entry point for Rekal."""

import argparse
import sys

from .config import load_config
from .core import RekalStore


def format_age(days: float) -> str:
    if days < 1:
        hours = max(1, int(days * 24))
        return f"{hours}h ago"
    if days < 7:
        return f"{int(days)}d ago"
    if days < 30:
        return f"{int(days / 7)}w ago"
    if days < 365:
        return f"{int(days / 30)}mo ago"
    return f"{int(days / 365)}y ago"


def unique_prefix(ids: list[str], floor: int = 8) -> int:
    """Return the minimum prefix length that makes all IDs in the list unique."""
    if len(ids) <= 1:
        return floor
    length = floor
    max_len = max(len(s) for s in ids)
    while length < max_len:
        if len(set(s[:length] for s in ids)) == len(ids):
            return length
        length += 1
    return max_len


def format_search_results(results: list[dict]) -> str:
    if not results:
        return "No results found."

    all_ids = [r.get("session_id", "") for r in results]
    prefix_len = unique_prefix(all_ids)

    lines = []
    for r in results:
        age = format_age(r.get("age_days", 0))
        workspace = r.get("workspace_path", "")
        if workspace:
            workspace = workspace.rstrip("/").rsplit("/", 1)[-1]

        title = r.get("title", "Untitled")
        tags = r.get("tags", "")
        desc = r.get("description", "")
        source = r.get("source", "claude")
        session_id = r.get("session_id", "")[:prefix_len]

        header = f"## {title} ({age}"
        if workspace:
            header += f", {workspace}"
        header += f", {source})"

        lines.append(header)
        if tags:
            lines.append(f"Tags: {tags}")
        if desc:
            lines.append(desc)
        lines.append(f"Session: {session_id}")
        lines.append("")

    return "\n".join(lines)


def format_recent_sessions(sessions: list[dict]) -> str:
    if not sessions:
        return "No sessions found."

    all_ids = [s.get("session_id", "") for s in sessions]
    prefix_len = unique_prefix(all_ids)

    lines = []
    for s in sessions:
        title = s.get("title") or "Untitled session"
        workspace = s.get("workspace_path", "")
        if workspace:
            workspace = workspace.rstrip("/").rsplit("/", 1)[-1]
        turns = s.get("turn_count", 0)
        started = s.get("started_at", "")[:16]
        source = s.get("source", "claude")
        sid = s.get("session_id", "")[:prefix_len]

        header = f"- **{title}** ({started}, {turns} turns, {source})"
        if workspace:
            header += f" [{workspace}]"
        header += f" `{sid}`"
        lines.append(header)

        if s.get("summary"):
            lines.append(f"  {s['summary']}")

    return "\n".join(lines)


def format_session_detail(detail: dict) -> str:
    if not detail:
        return "Session not found."

    lines = []
    title = detail.get("title") or "Untitled session"
    lines.append(f"# {title}")
    lines.append(f"Source: {detail.get('source', 'claude')}")
    lines.append(f"Workspace: {detail.get('workspace_path', 'unknown')}")
    lines.append(f"Started: {detail.get('started_at', '')}")
    if detail.get("summary"):
        lines.append(f"\n{detail['summary']}")
    lines.append(f"\n## Turns ({detail.get('turn_count', 0)})")

    for t in detail.get("turns", []):
        title = t.get("title", "Untitled")
        ts = t.get("timestamp", "")[:16]
        lines.append(f"\n### {title} ({ts})")
        if t.get("tags"):
            lines.append(f"Tags: {t['tags']}")
        if t.get("description"):
            lines.append(t["description"])

    return "\n".join(lines)


def format_stats(stats: dict) -> str:
    total = stats.get("total_sessions", 0)
    claude = stats.get("claude_sessions", 0)
    codex = stats.get("codex_sessions", 0)
    turns = stats.get("total_turns", 0)
    last = stats.get("last_indexed") or "never"
    searches = stats.get("total_searches", 0)
    hits = stats.get("searches_with_hits", 0)
    avg = stats.get("avg_results") or 0
    hit_rate = f"{hits / searches * 100:.0f}%" if searches > 0 else "—"

    lines = [
        "# Rekal Stats",
        "",
        f"Sessions: {total} ({claude} claude, {codex} codex)",
        f"Turns indexed: {turns}",
        f"Last indexed: {last}",
        "",
        f"Searches: {searches}",
        f"Hit rate: {hit_rate} ({hits}/{searches} returned results)",
        f"Avg results per search: {avg:.1f}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Rekal — search your coding session history")
    parser.add_argument("query", nargs="*", help="Search query")
    parser.add_argument("--recent", type=int, nargs="?", const=10, default=None,
                        help="Show N recent sessions (default 10)")
    parser.add_argument("--session", type=str, default=None,
                        help="Show detail for a specific session ID")
    parser.add_argument("--workspace", type=str, default=None,
                        help="Filter by workspace path")
    parser.add_argument("--limit", type=int, default=15,
                        help="Max results (default 15)")
    parser.add_argument("--stats", action="store_true",
                        help="Show usage statistics")
    args = parser.parse_args()

    config = load_config()
    store = RekalStore(config)

    try:
        if args.stats:
            print(format_stats(store.stats()))
        elif args.session:
            detail = store.session_detail(args.session)
            print(format_session_detail(detail))
        elif args.recent is not None:
            sessions = store.recent_sessions(args.workspace, args.recent)
            print(format_recent_sessions(sessions))
        elif args.query:
            query = " ".join(args.query)
            results = store.search(query, args.workspace, args.limit)
            print(format_search_results(results))
        else:
            # Default: show recent sessions
            sessions = store.recent_sessions(args.workspace, 10)
            print(format_recent_sessions(sessions))
    finally:
        store.close()


if __name__ == "__main__":
    main()
