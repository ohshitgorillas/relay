"""Per-run Codex hook configuration for Relay launches."""

import json
import os
import re
import shlex
from pathlib import Path

from relay.errors import ConfigError


def adapter_args(home: Path | None = None) -> list[str]:
    """Return the Codex overrides disabling Claude adapter hooks for this run."""
    if home is None:
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    source = home / "hooks.json"
    try:
        data = json.loads(source.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read Codex hooks {source}: {exc}") from exc

    states = []
    for event, groups in data.get("hooks", {}).items():
        event = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        for i, group in enumerate(groups):
            for j, hook in enumerate(group.get("hooks", [])):
                command = hook.get("command")
                if hook.get("type") != "command" or not isinstance(command, str):
                    continue
                try:
                    words = shlex.split(command)
                except ValueError as exc:
                    raise ConfigError(f"invalid Codex hook command in {source}: {exc}") from exc
                if not any(Path(word).name == "claude_adapter.py" for word in words):
                    continue
                # rust-v0.166.0: codex-rs/hooks/src/lib.rs:104,125 builds this key;
                # engine/discovery.rs:632,650 preserves the group/handler indices.
                key = f"{source}:{event}:{i}:{j}"
                states.append(f"{json.dumps(key, ensure_ascii=False)}={{enabled=false}}")
    return ["-c", "hooks.state={" + ",".join(states) + "}"] if states else []
