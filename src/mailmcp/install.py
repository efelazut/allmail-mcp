"""Register mailmcp in MCP clients' config files (user scope)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_COMMAND = ["uvx", "mailmcp"]
SERVER_NAME = "mail"


@dataclass
class ClientTarget:
    key: str            # 'claude' | 'codex' | 'cursor' | 'antigravity' | 'gemini'
    name: str           # human name
    path: Path          # config file
    fmt: str            # 'json-mcpServers' | 'codex-toml'
    detected: bool      # client looks installed (config dir exists or CLI on PATH)


@dataclass
class PlannedChange:
    target: ClientTarget
    action: str         # 'add' | 'update' | 'unchanged' | 'remove'
    before: str         # relevant snippet before
    after: str          # relevant snippet after


def targets(home: Path | None = None) -> list[ClientTarget]:
    """Known locations (home defaults to Path.home()):
    claude: ~/.claude.json (top-level "mcpServers", user scope)
    codex: ~/.codex/config.toml ([mcp_servers.mail])
    cursor: ~/.cursor/mcp.json ("mcpServers")
    antigravity: ~/.gemini/antigravity/mcp_config.json ("mcpServers")
    gemini: ~/.gemini/settings.json ("mcpServers")"""
    raise NotImplementedError


def plan(clients: list[str] | None, command: list[str] = DEFAULT_COMMAND, remove: bool = False,
         home: Path | None = None) -> list[PlannedChange]:
    """clients None = all detected. Never touches other keys/servers. Entry:
    JSON: {"command": cmd[0], "args": cmd[1:]} (claude also "type": "stdio").
    TOML: [mcp_servers.mail]\ncommand = "..."\nargs = [...]\nstartup_timeout_sec = 60"""
    raise NotImplementedError


def apply(changes: list[PlannedChange]) -> list[str]:
    """Backup each file to <file>.bak-mailmcp-<timestamp> before writing; JSON written with indent=2
    preserving other content; TOML edited textually (append or replace only our table) and validated
    with tomllib after writing (restore backup on failure). Return human lines of what happened."""
    raise NotImplementedError
