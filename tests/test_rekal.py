"""Lean, high-signal tests for Rekal core behaviors and regressions."""

import json
import os
import re
import tempfile
from pathlib import Path
from unittest import TestCase, main

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekal.config import RekalConfig, load_config
from rekal.core import RekalStore
from rekal.parser import parse_transcript, extract_latest_turn
from rekal.search import format_recent_sessions, format_search_results


def make_store(db_path: str | None = None) -> RekalStore:
    if db_path is None:
        fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
    return RekalStore(RekalConfig(db_path=db_path))


def seed_store(store: RekalStore) -> None:
    store.ensure_session(
        "session-abc123def456",
        source="claude",
        workspace_path="/Users/test/Projects/crustland",
    )
    store.store_turn(
        "session-abc123def456",
        1,
        "fix auth middleware",
        "fixed null check in token validation",
        "Fix auth middleware null check",
        "Status: completed\n- Fixed null check in auth handler",
        "authentication, middleware, jwt, bugfix",
    )
    store.store_turn(
        "session-abc123def456",
        2,
        "add rate limiting",
        "implemented sliding window limiter",
        "Add per-agent rate limiting",
        "Status: completed\n- Implemented sliding window algorithm",
        "api, rate-limiting, middleware",
    )

    store.ensure_session(
        "session-xyz789ghi000",
        source="codex",
        workspace_path="/Users/test/Projects/rekal",
    )
    store.store_turn(
        "session-xyz789ghi000",
        1,
        "set up SQLite FTS5 search",
        "created full-text index with BM25",
        "Initialize FTS5 search index",
        "Status: completed\n- Created FTS5 virtual table with triggers",
        "sqlite, fts5, search, database",
    )

    store.ensure_session(
        "session-jwt-debug-999",
        source="claude",
        workspace_path="/Users/test/Projects/crustland",
    )
    store.store_turn(
        "session-jwt-debug-999",
        1,
        "debug token expiry issue",
        "traced race condition in refresh flow",
        "Debug JWT token refresh race condition",
        "Status: in_progress\n- Found race in refresh flow",
        "authentication, jwt, debug, race-condition",
    )


class TestStoreCore(TestCase):
    def setUp(self):
        self.store = make_store()
        seed_store(self.store)

    def tearDown(self):
        db_path = self.store.config.db_path
        self.store.close()
        os.unlink(db_path)

    def test_search_and_detail_happy_path(self):
        results = self.store.search("authentication")
        self.assertGreater(len(results), 0)
        detail = self.store.session_detail("session-abc1")
        self.assertIsNotNone(detail)
        self.assertEqual(detail["session_id"], "session-abc123def456")
        self.assertEqual(len(detail["turns"]), 2)

    def test_session_prefix_ambiguity_returns_none(self):
        self.assertIsNone(self.store.session_detail("session-"))

    def test_search_invalid_queries_do_not_raise(self):
        for query in ["", '"', "foo OR", "(auth AND) OR NOT"]:
            with self.subTest(query=query):
                results = self.store.search(query)
                self.assertIsInstance(results, list)

    def test_turn_count_no_drift_on_replace(self):
        self.store.ensure_session("drift-test", source="claude")
        self.store.store_turn("drift-test", 1, "msg", "reply", "T1", "D1", "tag1")
        self.store.store_turn("drift-test", 1, "msg2", "reply2", "T2", "D2", "tag2")
        session = self.store.conn.execute(
            "SELECT turn_count FROM sessions WHERE session_id = 'drift-test'",
        ).fetchone()
        self.assertEqual(session["turn_count"], 1)
        turns = self.store.get_session_turns("drift-test")
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["title"], "T2")


class TestParser(TestCase):
    def _write_transcript(self, entries: list[dict], raw_lines: list[str] | None = None) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
            for line in raw_lines or []:
                f.write(line + "\n")
        return path

    def test_parse_and_extract_latest_turn(self):
        path = self._write_transcript([
            {"type": "user", "message": {"content": "First task"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Done with first."},
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/src/a.py"}},
            ]}},
            {"type": "user", "message": {"content": "Second task"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Done with second."},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/src/b.py"}},
            ]}},
        ])
        try:
            parsed = parse_transcript(path)
            self.assertEqual(parsed["turn_count"], 2)
            self.assertIn("First task", parsed["prompts"])
            self.assertIn("[Write: /src/a.py]", parsed["edits"])

            latest = extract_latest_turn(path)
            self.assertEqual(latest["turn_number"], 2)
            self.assertEqual(latest["prompt"], "Second task")
            self.assertIn("Done with second", latest["response"])
            self.assertIn("[Edit: /src/b.py]", latest["edits"])
        finally:
            os.unlink(path)

    def test_empty_or_missing_transcript(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            empty_path = f.name
        try:
            parsed_empty = parse_transcript(empty_path)
            self.assertEqual(parsed_empty["turn_count"], 0)
            self.assertEqual(parsed_empty["prompts"], "")
            latest_empty = extract_latest_turn(empty_path)
            self.assertEqual(latest_empty["turn_number"], 0)
            self.assertEqual(latest_empty["prompt"], "")
        finally:
            os.unlink(empty_path)

        parsed_missing = parse_transcript("/nonexistent/file.jsonl")
        latest_missing = extract_latest_turn("/nonexistent/file.jsonl")
        self.assertEqual(parsed_missing["turn_count"], 0)
        self.assertEqual(latest_missing["turn_number"], 0)

    def test_malformed_lines_are_skipped(self):
        path = self._write_transcript(
            [{"type": "user", "message": {"content": "valid"}}],
            raw_lines=["this is not json"],
        )
        try:
            result = parse_transcript(path)
            self.assertEqual(result["turn_count"], 1)
            self.assertIn("valid", result["prompts"])
        finally:
            os.unlink(path)


class TestFormatters(TestCase):
    def test_search_results_display_unique_session_ids(self):
        results = [
            {"title": "A", "tags": "", "description": "", "age_days": 1,
             "workspace_path": "", "source": "claude",
             "session_id": "codex-ab123456-first"},
            {"title": "B", "tags": "", "description": "", "age_days": 2,
             "workspace_path": "", "source": "claude",
             "session_id": "codex-ab123456-second"},
        ]
        output = format_search_results(results)
        shown = [line.split("Session: ")[1] for line in output.splitlines() if line.startswith("Session: ")]
        self.assertEqual(len(shown), 2)
        self.assertNotEqual(shown[0], shown[1])

    def test_recent_sessions_display_unique_session_ids(self):
        sessions = [
            {"title": "A", "session_id": "claude-xy987654-aaa", "source": "claude",
             "turn_count": 1, "started_at": "2025-01-01T00:00"},
            {"title": "B", "session_id": "claude-xy987654-bbb", "source": "claude",
             "turn_count": 2, "started_at": "2025-01-02T00:00"},
        ]
        output = format_recent_sessions(sessions)
        ids = re.findall(r"`([^`]+)`", output)
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])


class TestConfig(TestCase):
    def test_defaults(self):
        config = RekalConfig()
        self.assertEqual(config.provider, "claude")
        self.assertEqual(config.model, "haiku")
        self.assertTrue(config.enabled)
        self.assertEqual(config.timeout, 30)

    def test_load_missing_file_uses_defaults(self):
        config = load_config(Path("/nonexistent/config.yaml"))
        self.assertEqual(config.provider, "claude")

    def test_load_filters_unknown_keys(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("provider: codex\nmodel: o4-mini\nunknown_key: nope\n")
            path = Path(f.name)
        try:
            config = load_config(path)
            self.assertEqual(config.provider, "codex")
            self.assertEqual(config.model, "o4-mini")
            self.assertFalse(hasattr(config, "unknown_key"))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
