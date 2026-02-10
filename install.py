#!/usr/bin/env python3
"""Rekal installer — auto-configures hooks for Claude Code and Codex."""

import json
import os
import shutil
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
REKAL_DIR = Path.home() / ".rekal"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CLAUDE_SKILLS = Path.home() / ".claude" / "skills"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
CODEX_SKILLS = Path.home() / ".codex" / "skills"

HOOKS_DIR = REPO_DIR / "hooks"

# Hook definitions for Claude Code settings.json
# Each value is a single hook object (will be wrapped in matcher group if needed)
CLAUDE_HOOKS = {
    "Stop": {
        "type": "command",
        "command": f"python3 {HOOKS_DIR / 'on_turn_complete.py'}",
        "async": True,
        "timeout": 30000,
    },
    "SessionEnd": {
        "type": "command",
        "command": f"python3 {HOOKS_DIR / 'on_session_end.py'}",
        "async": True,
        "timeout": 30000,
    },
    "UserPromptSubmit": {
        "type": "command",
        "command": f"python3 {HOOKS_DIR / 'on_prompt.py'}",
        "async": True,
        "timeout": 15000,
    },
}

MARKER = "# rekal-hook"


def step(msg: str):
    print(f"  -> {msg}")


def _hooks_contain_rekal(hook_list: list) -> bool:
    """Check if 'rekal' appears in any hook command, handling both formats."""
    for h in hook_list:
        if not isinstance(h, dict):
            continue
        # Flat format: {"type": "command", "command": "..."}
        if "rekal" in h.get("command", ""):
            return True
        # Matcher format: {"matcher": "", "hooks": [{"command": "..."}]}
        for inner in h.get("hooks", []):
            if isinstance(inner, dict) and "rekal" in inner.get("command", ""):
                return True
    return False


def install_rekal_dir():
    """Create ~/.rekal/ with config and database."""
    REKAL_DIR.mkdir(parents=True, exist_ok=True)

    config_path = REKAL_DIR / "config.yaml"
    if not config_path.exists():
        shutil.copy(REPO_DIR / "config.template.yaml", config_path)
        step(f"Created {config_path}")
    else:
        step(f"Config already exists at {config_path}")

    # Initialize database by importing core (triggers schema creation)
    sys.path.insert(0, str(REPO_DIR))
    from rekal.config import load_config
    from rekal.core import RekalStore
    config = load_config()
    store = RekalStore(config)
    store.close()
    step(f"Database ready at {config.db_path_resolved}")


def install_claude_hooks():
    """Add async hooks to ~/.claude/settings.json."""
    if not CLAUDE_SETTINGS.parent.exists():
        step("Claude Code not found, skipping hooks")
        return

    if CLAUDE_SETTINGS.exists():
        with open(CLAUDE_SETTINGS) as f:
            settings = json.load(f)
    else:
        settings = {}

    hooks = settings.get("hooks", {})
    modified = False

    for event, hook_obj in CLAUDE_HOOKS.items():
        existing = hooks.get(event, [])

        # Check if rekal hook already installed (handles both flat and matcher formats)
        if _hooks_contain_rekal(existing):
            step(f"Claude {event} hook already installed")
            continue

        # Detect format: matcher groups have "hooks" key, flat hooks have "type" key
        uses_matcher = any(isinstance(h, dict) and "hooks" in h for h in existing)

        if uses_matcher or not existing:
            # Wrap in matcher group to match existing format
            existing.append({
                "matcher": "",
                "hooks": [hook_obj],
            })
        else:
            existing.append(hook_obj)

        hooks[event] = existing
        modified = True
        step(f"Added Claude {event} async hook")

    if modified:
        settings["hooks"] = hooks
        with open(CLAUDE_SETTINGS, "w") as f:
            json.dump(settings, f, indent=2)
        step(f"Updated {CLAUDE_SETTINGS}")


def install_claude_skill():
    """Install the /rekal skill into Claude Code skills."""
    skill_dir = CLAUDE_SKILLS / "rekal"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dest = skill_dir / "SKILL.md"
    skill_source = REPO_DIR / "skills" / "rekal" / "SKILL.md"

    content = skill_source.read_text()
    content = content.replace("$REKAL_REPO", str(REPO_DIR))
    skill_dest.write_text(content)
    step(f"Installed /rekal skill at {skill_dest}")


def install_codex_hook():
    """Add notify hook to ~/.codex/config.toml."""
    if not CODEX_CONFIG.parent.exists():
        step("Codex not found, skipping hook")
        return

    hook_cmd = f'python3 {HOOKS_DIR / "on_codex_turn.py"}'

    if CODEX_CONFIG.exists():
        content = CODEX_CONFIG.read_text()
    else:
        content = ""

    # Check if already installed
    if "rekal" in content:
        step("Codex notify hook already installed")
        return

    # Check if there's an existing notify line
    lines = content.split("\n")
    new_lines = []
    found_notify = False
    for line in lines:
        if line.strip().startswith("notify") and "=" in line:
            # Replace existing notify hook
            new_lines.append(f'notify = "{hook_cmd}"  {MARKER}')
            found_notify = True
            step("Replaced existing Codex notify hook")
        else:
            new_lines.append(line)

    if not found_notify:
        new_lines.append(f'notify = "{hook_cmd}"  {MARKER}')
        step("Added Codex notify hook")

    CODEX_CONFIG.write_text("\n".join(new_lines))
    step(f"Updated {CODEX_CONFIG}")


def install_codex_skill():
    """Install the rekal skill into Codex skills."""
    if not CODEX_SKILLS.parent.exists():
        step("Codex not found, skipping skill")
        return

    skill_dir = CODEX_SKILLS / "rekal"
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_source = REPO_DIR / "skills" / "rekal" / "SKILL.md"
    content = skill_source.read_text()
    content = content.replace("$REKAL_REPO", str(REPO_DIR))
    (skill_dir / "SKILL.md").write_text(content)
    step(f"Installed Codex skill at {skill_dir}")


def check_cli_available():
    """Verify that the configured CLI (claude or codex) is available."""
    import shutil
    sys.path.insert(0, str(REPO_DIR))
    from rekal.config import load_config
    config = load_config()

    cli = config.provider  # "claude" or "codex"
    if shutil.which(cli):
        step(f"Using {cli} CLI with model '{config.model}'")
    else:
        print(f"\n  WARNING: '{cli}' not found in PATH")
        print(f"  Install it or change provider in {REKAL_DIR / 'config.yaml'}")

    # Check for the other CLI too
    other = "codex" if cli == "claude" else "claude"
    if shutil.which(other):
        step(f"{other} also available (change provider in config.yaml to use it)")


def main():
    print("Rekal installer")
    print("=" * 40)
    print()

    print("[1/6] Setting up ~/.rekal/")
    install_rekal_dir()
    print()

    print("[2/6] Configuring Claude Code hooks")
    install_claude_hooks()
    print()

    print("[3/6] Installing Claude Code /rekal skill")
    install_claude_skill()
    print()

    print("[4/6] Configuring Codex hook")
    install_codex_hook()
    print()

    print("[5/6] Installing Codex skill")
    install_codex_skill()
    print()

    print("[6/6] Checking CLI availability")
    check_cli_available()
    print()

    print("=" * 40)
    print("Rekal installed successfully!")
    print()
    print("Next steps:")
    print(f"  1. Edit {REKAL_DIR / 'config.yaml'} if needed")
    print("  2. Start a Claude Code session — hooks will capture automatically")
    print("  3. Use /rekal <query> to search your history")
    print()
    print("To uninstall: python3 uninstall.py")


if __name__ == "__main__":
    main()
