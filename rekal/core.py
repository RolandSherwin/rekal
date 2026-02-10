"""SQLite store with FTS5 and scored search."""

import logging
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import RekalConfig, load_config

log = logging.getLogger("rekal")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'claude',
    workspace_path TEXT,
    model TEXT,
    title TEXT,
    summary TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    turn_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    turn_number INTEGER,
    user_message TEXT,
    agent_output TEXT,
    title TEXT,
    description TEXT,
    tags TEXT,
    model_name TEXT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, turn_number)
);

CREATE TABLE IF NOT EXISTS search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    result_count INTEGER DEFAULT 0,
    workspace TEXT,
    searched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_timestamp ON turns(timestamp);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_path);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    title,
    description,
    tags,
    user_message,
    content='turns',
    content_rowid='id'
);

"""

# Triggers must be created separately (no IF NOT EXISTS for triggers)
TRIGGERS = [
    ("turns_ai", """
        CREATE TRIGGER turns_ai AFTER INSERT ON turns BEGIN
            INSERT INTO turns_fts(rowid, title, description, tags, user_message)
            VALUES (new.id, new.title, new.description, new.tags, new.user_message);
        END;
    """),
    ("turns_ad", """
        CREATE TRIGGER turns_ad AFTER DELETE ON turns BEGIN
            INSERT INTO turns_fts(turns_fts, rowid, title, description, tags, user_message)
            VALUES ('delete', old.id, old.title, old.description, old.tags, old.user_message);
        END;
    """),
    ("turns_au", """
        CREATE TRIGGER turns_au AFTER UPDATE ON turns BEGIN
            INSERT INTO turns_fts(turns_fts, rowid, title, description, tags, user_message)
            VALUES ('delete', old.id, old.title, old.description, old.tags, old.user_message);
            INSERT INTO turns_fts(rowid, title, description, tags, user_message)
            VALUES (new.id, new.title, new.description, new.tags, new.user_message);
        END;
    """),
]


class RekalStore:
    def __init__(self, config: RekalConfig | None = None):
        self.config = config or load_config()
        db_path = self.config.db_path_resolved
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.executescript(FTS_SCHEMA)
        for trigger_name, trigger_sql in TRIGGERS:
            exists = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
                (trigger_name,),
            ).fetchone()
            if not exists:
                self.conn.executescript(trigger_sql)
        self.conn.commit()

    def ensure_session(self, session_id: str, source: str = "claude",
                       workspace_path: str | None = None,
                       model: str | None = None) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO sessions (session_id, source, workspace_path, model)
               VALUES (?, ?, ?, ?)""",
            (session_id, source, workspace_path, model),
        )
        self.conn.commit()

    def store_turn(self, session_id: str, turn_number: int,
                   user_message: str, agent_output: str,
                   title: str, description: str, tags: str,
                   model_name: str | None = None) -> int:
        # Check if this turn already exists (avoid inflating turn_count)
        existing = self.conn.execute(
            "SELECT 1 FROM turns WHERE session_id = ? AND turn_number = ?",
            (session_id, turn_number),
        ).fetchone()
        cur = self.conn.execute(
            """INSERT OR REPLACE INTO turns
               (session_id, turn_number, user_message, agent_output,
                title, description, tags, model_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, turn_number, user_message, agent_output,
             title, description, tags, model_name),
        )
        if not existing:
            self.conn.execute(
                "UPDATE sessions SET turn_count = turn_count + 1 WHERE session_id = ?",
                (session_id,),
            )
        self.conn.commit()
        return cur.lastrowid

    def update_session_summary(self, session_id: str, title: str,
                               summary: str) -> None:
        self.conn.execute(
            """UPDATE sessions SET title = ?, summary = ?, ended_at = datetime('now')
               WHERE session_id = ?""",
            (title, summary, session_id),
        )
        self.conn.commit()

    def get_session_turns(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT title, description, tags, user_message, timestamp
               FROM turns WHERE session_id = ? ORDER BY turn_number""",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """Escape raw user input into safe FTS5 query tokens."""
        # Split into words, quote each token to avoid FTS syntax errors
        tokens = query.split()
        if not tokens:
            return '""'
        return " ".join(f'"{t}"' for t in tokens if t.strip())

    def search(self, query: str, workspace: str | None = None,
               limit: int = 20) -> list[dict]:
        """Scored FTS5 search: BM25 × recency × workspace bonus."""
        safe_query = self._sanitize_fts_query(query)
        try:
            rows = self.conn.execute(
                """SELECT t.id, t.session_id, t.title, t.description, t.tags,
                          t.user_message, t.timestamp,
                          s.workspace_path, s.source,
                          bm25(turns_fts) as rank
                   FROM turns_fts
                   JOIN turns t ON t.id = turns_fts.rowid
                   JOIN sessions s ON s.session_id = t.session_id
                   WHERE turns_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, limit * 3),  # Over-fetch for re-ranking
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        now = datetime.now(timezone.utc)
        scored = []
        for row in rows:
            row_dict = dict(row)
            # BM25 returns negative values (closer to 0 = better)
            bm25_score = -row_dict["rank"]

            # Recency: exponential decay with ~30 day half-life
            try:
                ts = datetime.fromisoformat(row_dict["timestamp"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                days_old = (now - ts).total_seconds() / 86400
            except (ValueError, TypeError):
                days_old = 365  # Fallback for bad timestamps
            recency = math.exp(-days_old / 30)

            # Workspace bonus
            ws_bonus = 2.0 if (workspace and row_dict.get("workspace_path")
                               and workspace in row_dict["workspace_path"]) else 1.0

            row_dict["score"] = bm25_score * recency * ws_bonus
            row_dict["age_days"] = round(days_old, 1)
            scored.append(row_dict)

        scored.sort(key=lambda x: x["score"], reverse=True)
        results = scored[:limit]

        # Log the search
        try:
            self.conn.execute(
                "INSERT INTO search_log (query, result_count, workspace) VALUES (?, ?, ?)",
                (query, len(results), workspace),
            )
            self.conn.commit()
        except Exception as e:
            log.debug("search_log insert failed: %s", e)

        return results

    def recent_sessions(self, workspace: str | None = None,
                        limit: int = 10) -> list[dict]:
        if workspace:
            rows = self.conn.execute(
                """SELECT session_id, source, workspace_path, title, summary,
                          started_at, ended_at, turn_count
                   FROM sessions
                   WHERE workspace_path LIKE ?
                   ORDER BY started_at DESC LIMIT ?""",
                (f"%{workspace}%", limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT session_id, source, workspace_path, title, summary,
                          started_at, ended_at, turn_count
                   FROM sessions
                   ORDER BY started_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def session_detail(self, session_id: str) -> dict | None:
        # Try exact match first, then prefix match for truncated IDs
        session = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not session:
            matches = self.conn.execute(
                "SELECT * FROM sessions WHERE session_id LIKE ?",
                (session_id + "%",),
            ).fetchall()
            if len(matches) == 1:
                session = matches[0]
            elif len(matches) > 1:
                # Ambiguous prefix — return None so caller can handle it
                return None
        if not session:
            return None
        result = dict(session)
        resolved_id = result["session_id"]
        result["turns"] = self.get_session_turns(resolved_id)
        return result

    def stats(self) -> dict:
        """Return usage statistics."""
        row = self.conn.execute(
            """SELECT
                (SELECT COUNT(*) FROM sessions) as total_sessions,
                (SELECT COUNT(*) FROM sessions WHERE source = 'claude') as claude_sessions,
                (SELECT COUNT(*) FROM sessions WHERE source = 'codex') as codex_sessions,
                (SELECT COUNT(*) FROM turns) as total_turns,
                (SELECT MAX(timestamp) FROM turns) as last_indexed,
                (SELECT COUNT(*) FROM search_log) as total_searches,
                (SELECT COUNT(*) FROM search_log WHERE result_count > 0) as searches_with_hits,
                (SELECT AVG(result_count) FROM search_log) as avg_results"""
        ).fetchone()
        return dict(row)

    def close(self):
        self.conn.close()
