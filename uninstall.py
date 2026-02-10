#!/usr/bin/env python3
"""Rekal uninstaller — cleanly removes all hooks and skills."""

import json
import sys
from pathlib import Path

REKAL_DIR = Path.home() / ".rekal"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CLAUDE_SKILLS = Path.home() / ".claude" / "skills" / "rekal"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
CODEX_SKILLS = Path.home() / ".codex" / "skills" / "rekal"


def step(msg: str):
    print(f"  -> {msg}")


def remove_claude_hooks():
    if not CLAUDE_SETTINGS.exists():
        step("No Claude settings found")
        return

    with open(CLAUDE_SETTINGS) as f:
        settings = json.load(f)

    hooks = settings.get("hooks", {})
    modified = False

    for event in list(hooks.keys()):
        original = hooks[event]
        filtered = [
            h for h in original
            if not (isinstance(h, dict) and "rekal" in h.get("command", ""))
        ]
        if len(filtered) != len(original):
            hooks[event] = filtered
            if not filtered:
                del hooks[event]
            modified = True
            step(f"Removed Claude {event} hook")

    if modified:
        settings["hooks"] = hooks
        with open(CLAUDE_SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
    else:
        step("No Claude hooks to remove")


def remove_claude_skill():
    if CLAUDE_SKILLS.exists() or CLAUDE_SKILLS.is_symlink():
        if CLAUDE_SKILLS.is_symlink():
            CLAUDE_SKILLS.unlink()
        else:
            import shutil
            shutil.rmtree(CLAUDE_SKILLS)
        step("Removed /rekal skill")
    else:
        step("No Claude skill to remove")


def remove_codex_hook():
    if not CODEX_CONFIG.exists():
        step("No Codex config found")
        return

    content = CODEX_CONFIG.read_text()
    lines = content.split("\n")
    new_lines = [l for l in lines if "rekal" not in l]

    if len(new_lines) != len(lines):
        CODEX_CONFIG.write_text("\n".join(new_lines))
        step("Removed Codex notify hook")
    else:
        step("No Codex hook to remove")


def remove_codex_skill():
    if CODEX_SKILLS.exists() or CODEX_SKILLS.is_symlink():
        if CODEX_SKILLS.is_symlink():
            CODEX_SKILLS.unlink()
        else:
            import shutil
            shutil.rmtree(CODEX_SKILLS)
        step("Removed Codex skill")
    else:
        step("No Codex skill to remove")


def main():
    print("Rekal uninstaller")
    print("=" * 40)
    print()

    print("[1/4] Removing Claude Code hooks")
    remove_claude_hooks()
    print()

    print("[2/4] Removing Claude Code skill")
    remove_claude_skill()
    print()

    print("[3/4] Removing Codex hook")
    remove_codex_hook()
    print()

    print("[4/4] Removing Codex skill")
    remove_codex_skill()
    print()

    print("=" * 40)
    print("Hooks and skills removed.")
    print()

    if REKAL_DIR.exists():
        print(f"Your data is still at {REKAL_DIR}/")
        print("To remove it completely: rm -rf ~/.rekal")
    print()
    print("Rekal uninstalled cleanly.")


if __name__ == "__main__":
    main()
