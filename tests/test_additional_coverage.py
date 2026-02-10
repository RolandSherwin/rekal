"""Additional coverage for non-critical paths."""

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install
from rekal.config import RekalConfig, load_config
from rekal.core import RekalStore
from rekal.llm import _call_claude, _call_codex
from rekal.parser import extract_latest_turn, parse_transcript
from rekal.search import format_session_detail, format_stats


def make_store() -> tuple[RekalStore, str]:
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    return RekalStore(RekalConfig(db_path=db_path)), db_path


class TestSearchFormatters(TestCase):
    def test_format_stats_handles_zero_searches(self):
        output = format_stats({
            "total_sessions": 0,
            "claude_sessions": 0,
            "codex_sessions": 0,
            "total_turns": 0,
            "last_indexed": None,
            "total_searches": 0,
            "searches_with_hits": 0,
            "avg_results": None,
        })
        self.assertIn("Searches: 0", output)
        self.assertIn("0/0 returned results", output)
        self.assertIn("Avg results per search: 0.0", output)

    def test_format_session_detail_populated_and_missing(self):
        output = format_session_detail({
            "title": "Stabilize indexing",
            "source": "codex",
            "workspace_path": "/tmp/project",
            "started_at": "2026-02-01 09:00:00",
            "summary": "Wrapped up indexing fixes.",
            "turn_count": 1,
            "turns": [{
                "title": "Fix search logging",
                "timestamp": "2026-02-01 09:10:00",
                "tags": "sqlite, logging",
                "description": "- Added debug logging for failed inserts",
            }],
        })
        self.assertIn("# Stabilize indexing", output)
        self.assertIn("## Turns (1)", output)
        self.assertIn("Tags: sqlite, logging", output)
        self.assertEqual(format_session_detail({}), "Session not found.")


class TestCoreAdditional(TestCase):
    def setUp(self):
        self.store, self.db_path = make_store()

        self.store.ensure_session(
            "sess-a",
            source="claude",
            workspace_path="/Users/test/Projects/crustland",
        )
        self.store.store_turn(
            "sess-a",
            1,
            "debug auth",
            "fixed bug",
            "Fix auth bug",
            "- Added null check",
            "auth, bugfix",
        )
        self.store.ensure_session(
            "sess-b",
            source="codex",
            workspace_path="/Users/test/Projects/rekal",
        )
        self.store.store_turn(
            "sess-b",
            1,
            "add index",
            "done",
            "Add index",
            "- Added index",
            "sqlite, fts",
        )
        self.store.conn.execute(
            "UPDATE sessions SET started_at = ? WHERE session_id = ?",
            ("2026-02-01 00:00:00", "sess-a"),
        )
        self.store.conn.execute(
            "UPDATE sessions SET started_at = ? WHERE session_id = ?",
            ("2026-02-02 00:00:00", "sess-b"),
        )
        self.store.conn.commit()

    def tearDown(self):
        self.store.close()
        os.unlink(self.db_path)

    def test_recent_sessions_workspace_filter(self):
        rows = self.store.recent_sessions(workspace="crustland", limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "sess-a")
        self.assertEqual(self.store.recent_sessions(workspace="no-match"), [])

    def test_stats_aggregation_values(self):
        # Add an orphan session (no turns) — should be excluded from counts
        self.store.ensure_session("sess-orphan", source="claude", workspace_path="/tmp")

        self.store.conn.execute(
            "INSERT INTO search_log (query, result_count, workspace) VALUES (?, ?, ?)",
            ("auth", 2, "crustland"),
        )
        self.store.conn.execute(
            "INSERT INTO search_log (query, result_count, workspace) VALUES (?, ?, ?)",
            ("none", 0, None),
        )
        self.store.conn.commit()

        stats = self.store.stats()
        self.assertEqual(stats["total_sessions"], 2)  # orphan excluded
        self.assertEqual(stats["claude_sessions"], 1)
        self.assertEqual(stats["codex_sessions"], 1)
        self.assertEqual(stats["total_turns"], 2)
        self.assertIsNotNone(stats["last_indexed"])
        self.assertEqual(stats["total_searches"], 2)
        self.assertEqual(stats["searches_with_hits"], 1)
        self.assertAlmostEqual(stats["avg_results"], 1.0)


class TestParserSkipTools(TestCase):
    def _write_transcript(self, entries: list[dict]) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")
        return path

    def test_skip_tools_are_not_stored_in_edits(self):
        transcript = self._write_transcript([
            {"type": "user", "message": {"content": [{"type": "text", "text": "task one"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/tmp/ignored.py"}},
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/tmp/kept.py"}},
            ]}},
            {"type": "user", "message": {"content": "task two"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "WebSearch", "input": {"query": "ignored"}},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/tmp/kept2.py"}},
            ]}},
        ])
        try:
            parsed = parse_transcript(transcript)
            self.assertEqual(parsed["turn_count"], 2)
            self.assertIn("[Write: /tmp/kept.py]", parsed["edits"])
            self.assertIn("[Edit: /tmp/kept2.py]", parsed["edits"])
            self.assertNotIn("ignored.py", parsed["edits"])

            latest = extract_latest_turn(transcript)
            self.assertEqual(latest["turn_number"], 2)
            self.assertIn("[Edit: /tmp/kept2.py]", latest["edits"])
            self.assertNotIn("WebSearch", latest["edits"])
        finally:
            os.unlink(transcript)


class TestConfigFallback(TestCase):
    def test_load_config_without_yaml(self):
        fd, path_str = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w") as f:
            f.write(
                "provider: codex\n"
                "model: o4-mini\n"
                "enabled: false\n"
                "timeout: 45\n"
                "max_prompt_chars: 1234\n"
                "unknown_key: ignored\n"
            )
        path = Path(path_str)
        try:
            with patch("rekal.config.HAS_YAML", False):
                config = load_config(path)
            self.assertEqual(config.provider, "codex")
            self.assertEqual(config.model, "o4-mini")
            self.assertFalse(config.enabled)
            self.assertEqual(config.timeout, 45)
            self.assertEqual(config.max_prompt_chars, 1234)
            self.assertFalse(hasattr(config, "unknown_key"))
        finally:
            path.unlink(missing_ok=True)


class TestLLMParsing(TestCase):
    def test_call_claude_parses_wrapped_json_result(self):
        stdout = json.dumps({
            "type": "result",
            "result": json.dumps({
                "title": "Fix auth race",
                "description": "Patched token refresh logic.",
                "tags": ["auth", "jwt"],
            }),
        })
        result = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        config = RekalConfig(provider="claude", model="haiku", timeout=1)

        with patch("rekal.llm.subprocess.run", return_value=result):
            parsed = _call_claude("system", "user", config)
            self.assertEqual(parsed["title"], "Fix auth race")
            self.assertEqual(parsed["tags"], ["auth", "jwt"])

    def test_call_codex_extracts_assistant_text_from_jsonl(self):
        payload = json.dumps({
            "title": "Add search stats",
            "description": "Added metrics summary.",
            "tags": "search, metrics",
        })
        stdout = "\n".join([
            json.dumps({"type": "status", "message": "running"}),
            "not-json",
            json.dumps({
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": payload}],
            }),
        ])
        result = SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        config = RekalConfig(provider="codex", model="o4-mini", timeout=1)

        with patch("rekal.llm.subprocess.run", return_value=result):
            parsed = _call_codex("system", "user", config)
            self.assertEqual(parsed["title"], "Add search stats")
            self.assertEqual(parsed["tags"], "search, metrics")


class TestInstallHooks(TestCase):
    @staticmethod
    def _event_commands(event_hooks: list[dict]) -> list[str]:
        commands = []
        for item in event_hooks:
            if not isinstance(item, dict):
                continue
            cmd = item.get("command")
            if isinstance(cmd, str):
                commands.append(cmd)
            for inner in item.get("hooks", []):
                if isinstance(inner, dict) and isinstance(inner.get("command"), str):
                    commands.append(inner["command"])
        return commands

    def test_install_claude_hooks_mixed_format_and_idempotency(self):
        tmpdir = Path(tempfile.mkdtemp(prefix="rekal_install_"))
        settings_path = tmpdir / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [
                    {"type": "command", "command": "python3 /tmp/other-stop.py"},
                ],
                "SessionEnd": [
                    {
                        "matcher": "",
                        "hooks": [
                            {"type": "command", "command": "python3 /tmp/other-session.py"},
                        ],
                    },
                ],
            },
        }, indent=2))

        old_settings = install.CLAUDE_SETTINGS
        install.CLAUDE_SETTINGS = settings_path
        try:
            with patch("install.step"):
                install.install_claude_hooks()
                first = json.loads(settings_path.read_text())

                stop_cmds = self._event_commands(first["hooks"]["Stop"])
                session_cmds = self._event_commands(first["hooks"]["SessionEnd"])

                self.assertIn("python3 /tmp/other-stop.py", stop_cmds)
                self.assertIn("python3 /tmp/other-session.py", session_cmds)
                self.assertEqual(sum("rekal" in cmd for cmd in stop_cmds), 1)
                self.assertEqual(sum("rekal" in cmd for cmd in session_cmds), 1)
                self.assertNotIn("UserPromptSubmit", first["hooks"])

                install.install_claude_hooks()
                second = json.loads(settings_path.read_text())

            for event in ("Stop", "SessionEnd"):
                commands = self._event_commands(second["hooks"][event])
                self.assertEqual(sum("rekal" in cmd for cmd in commands), 1)
        finally:
            install.CLAUDE_SETTINGS = old_settings
            settings_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
