"""Configuration loader for Rekal."""

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


REKAL_DIR = Path.home() / ".rekal"
DEFAULT_CONFIG_PATH = REKAL_DIR / "config.yaml"
DEFAULT_DB_PATH = REKAL_DIR / "db.sqlite"


@dataclass
class RekalConfig:
    provider: str = "claude"           # "claude" or "codex"
    model: str = "haiku"               # claude: haiku/sonnet/opus, codex: o4-mini/o3/etc
    db_path: str = str(DEFAULT_DB_PATH)
    enabled: bool = True
    timeout: int = 30                  # CLI call timeout in seconds
    max_prompt_chars: int = 4000
    max_response_chars: int = 8000
    max_edit_chars: int = 2000

    @property
    def db_path_resolved(self) -> Path:
        return Path(self.db_path).expanduser()


def load_config(path: Path | None = None) -> RekalConfig:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return RekalConfig()

    if HAS_YAML:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return RekalConfig()
    else:
        # Minimal YAML-like parser for simple key: value configs
        data = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if value.lower() == "true":
                        value = True
                    elif value.lower() == "false":
                        value = False
                    elif value.isdigit():
                        value = int(value)
                    data[key] = value

    valid_fields = {f.name for f in RekalConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return RekalConfig(**filtered)
