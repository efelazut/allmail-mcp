"""Register mailmcp in MCP clients' config files (user scope)."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .errors import UsageError

DEFAULT_COMMAND = ["uvx", f"mailmcp@{__version__}"]
SERVER_NAME = "mail"
_STARTUP_TIMEOUT = 60


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
    error: str | None = None
    command: list[str] = field(default_factory=lambda: list(DEFAULT_COMMAND))
    name: str = SERVER_NAME


# --------------------------------------------------------------------------- targets

def targets(home: Path | None = None) -> list[ClientTarget]:
    """Known locations (home defaults to Path.home()):
    claude: ~/.claude.json (top-level "mcpServers", user scope)
    codex: ~/.codex/config.toml ([mcp_servers.mail])
    cursor: ~/.cursor/mcp.json ("mcpServers")
    antigravity: ~/.gemini/antigravity/mcp_config.json ("mcpServers")
    gemini: ~/.gemini/settings.json ("mcpServers")"""
    h = Path(home) if home is not None else Path.home()
    # (key, name, path, fmt, cli on PATH, parent dir counts as evidence)
    spec = [
        ("claude", "Claude Code", h / ".claude.json", "json-mcpServers", "claude", False),
        ("codex", "Codex", h / ".codex" / "config.toml", "codex-toml", "codex", True),
        ("cursor", "Cursor", h / ".cursor" / "mcp.json", "json-mcpServers", "cursor", True),
        ("antigravity", "Antigravity", h / ".gemini" / "antigravity" / "mcp_config.json",
         "json-mcpServers", "antigravity", True),
        # ~/.gemini also exists for Antigravity-only users, so it is not evidence for Gemini CLI.
        ("gemini", "Gemini CLI", h / ".gemini" / "settings.json", "json-mcpServers", "gemini", False),
    ]
    out = []
    for key, name, path, fmt, cli, parent_ok in spec:
        detected = path.exists() or (parent_ok and path.parent.is_dir()) or shutil.which(cli) is not None
        out.append(ClientTarget(key, name, path, fmt, bool(detected)))
    return out


# --------------------------------------------------------------------------- JSON

def _desired_json(target: ClientTarget, command: list[str]) -> dict:
    entry: dict = {}
    if target.key == "claude":
        entry["type"] = "stdio"
    entry["command"] = command[0]
    entry["args"] = list(command[1:])
    if target.key == "claude":
        entry["env"] = {}
    return entry


def _dump_json(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _snippet(entry) -> str:
    return "(none)" if entry is None else json.dumps(entry, indent=2, ensure_ascii=False)


def _looks_like_ours(entry) -> bool:
    """True when an existing server entry plausibly launches mailmcp."""
    if not isinstance(entry, dict):
        return False
    args = entry.get("args")
    parts = [str(entry.get("command", ""))] + ([str(a) for a in args] if isinstance(args, list) else [])
    return "mailmcp" in " ".join(parts).lower()


_FOREIGN = "an MCP server named '{name}' already exists and is not mailmcp; remove or rename it first"


def _compute_json(target: ClientTarget, command: list[str], remove: bool, name: str = SERVER_NAME):
    """Return (action, before, after, new_text | None, error)."""
    path = target.path
    data: dict = {}
    if path.exists():
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            return "unchanged", "", "", None, f"cannot read {path}: {e}"
        if raw.strip():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                return "unchanged", "", "", None, f"{path} is not valid JSON ({e}); left untouched"
            if not isinstance(data, dict):
                return "unchanged", "", "", None, f"{path} is not a JSON object; left untouched"
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        return "unchanged", "", "", None, f"'mcpServers' in {path} is not an object; left untouched"
    current = (servers or {}).get(name)
    before = _snippet(current)
    if current is not None and not _looks_like_ours(current):
        return "unchanged", before, before, None, _FOREIGN.format(name=name)

    if remove:
        if current is None:
            return "unchanged", before, before, None, None
        new = copy.deepcopy(data)
        del new["mcpServers"][name]
        return "remove", before, "(none)", _dump_json(new), None

    desired = _desired_json(target, command)
    if isinstance(current, dict):
        merged = {**current, **desired}
        if "env" in current:
            merged["env"] = current["env"]
    else:
        merged = desired
    after = _snippet(merged)
    if current is not None and merged == current:
        return "unchanged", before, after, None, None
    new = copy.deepcopy(data)
    if not isinstance(new.get("mcpServers"), dict):
        new["mcpServers"] = {}
    new["mcpServers"][name] = merged
    return ("add" if current is None else "update"), before, after, _dump_json(new), None


# --------------------------------------------------------------------------- TOML

_TOML_ESC = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _toml_str(s: str) -> str:
    out = []
    for ch in s:
        if ch in _TOML_ESC:
            out.append(_TOML_ESC[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _toml_key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else _toml_str(k)


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return _toml_str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(x)}" for k, x in v.items()) + " }"
    raise ValueError(f"unsupported TOML value type {type(v).__name__}")


_HEADER_RE = re.compile(r"^\s*(\[\[?)\s*([^\[\]]+?)\s*\]\]?\s*(?:#.*)?$")


def _header_name(line: str) -> str | None:
    """Normalized dotted table name if `line` is a table header, else None."""
    m = _HEADER_RE.match(line.rstrip("\r\n"))
    if not m:
        return None
    parts = [p.strip().strip('"').strip("'") for p in m.group(2).split(".")]
    return ".".join(parts)


def _is_ours(name: str | None, table: str) -> bool:
    return name is not None and (name == table or name.startswith(table + "."))


def _split_segments(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    segs: list[tuple[str | None, list[str]]] = [(None, [])]
    for ln in lines:
        name = _header_name(ln)
        if name is not None:
            segs.append((name, [ln]))
        else:
            segs[-1][1].append(ln)
    return segs


def _strip_trailing_blank(lines: list[str]) -> list[str]:
    lines = list(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def _mail_table(text: str, name: str = SERVER_NAME):
    data = tomllib.loads(text)
    servers = data.get("mcp_servers")
    if servers is None:
        return None
    if not isinstance(servers, dict):
        raise ValueError("'mcp_servers' is not a table")
    return servers.get(name)


def _compute_toml(target: ClientTarget, command: list[str], remove: bool, name: str = SERVER_NAME):
    table = f"mcp_servers.{_toml_key(name)}"
    norm = f"mcp_servers.{name}"
    path = target.path
    text = ""
    if path.exists():
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            return "unchanged", "", "", None, f"cannot read {path}: {e}"
    try:
        current = _mail_table(text, name)
    except (tomllib.TOMLDecodeError, ValueError) as e:
        return "unchanged", "", "", None, f"{path} is not valid TOML ({e}); left untouched"
    if current is not None and not isinstance(current, dict):
        return "unchanged", "", "", None, f"'mcp_servers.{name}' in {path} is not a table; left untouched"

    nl = "\r\n" if "\r\n" in text else "\n"
    if current is not None and not _looks_like_ours(current):
        return "unchanged", "", "", None, _FOREIGN.format(name=name)
    segs = _split_segments(text.splitlines(keepends=True))
    main_idx = next((i for i, (n, _) in enumerate(segs) if n == norm), None)
    if current is not None and not any(_is_ours(n, norm) for n, _ in segs):
        return ("unchanged", "", "", None,
                f"'{name}' in {path} uses a layout this tool will not edit; left untouched")

    before = "".join(segs[main_idx][1]).strip() if main_idx is not None else "(none)"

    if remove:
        if not any(_is_ours(n, norm) for n, _ in segs):
            return "unchanged", before, before, None, None
        kept = [s for s in segs if not _is_ours(s[0], norm)]
        new_text = "".join("".join(ls) for _, ls in kept)
        new_text = "".join(_strip_trailing_blank(new_text.splitlines(keepends=True)))
        if new_text and not new_text.endswith("\n"):
            new_text += nl
        return "remove", before, "(none)", new_text, None

    scalars = {k: v for k, v in (current or {}).items() if not isinstance(v, dict)}
    desired = {"command": command[0], "args": list(command[1:]), "startup_timeout_sec": _STARTUP_TIMEOUT}
    merged = {**scalars, **desired}
    if current is not None and main_idx is not None and merged == scalars:
        return "unchanged", before, before, None, None
    block_lines = [f"[{table}]"] + [f"{_toml_key(k)} = {_toml_value(v)}" for k, v in merged.items()]
    block = nl.join(block_lines) + nl
    after = block.strip()

    if main_idx is not None:
        is_last = main_idx == len(segs) - 1
        segs[main_idx] = (norm, [block] + ([] if is_last else [nl]))
        new_text = "".join("".join(ls) for _, ls in segs)
        action = "update"
    else:
        new_text = text
        if new_text and not new_text.endswith("\n"):
            new_text += nl
        if new_text.strip():
            new_text += nl
        new_text += block
        action = "add"
    try:
        check = _mail_table(new_text, name)
    except (tomllib.TOMLDecodeError, ValueError) as e:
        return "unchanged", before, after, None, f"edit would produce invalid TOML ({e}); left untouched"
    if not isinstance(check, dict) or any(check.get(k) != v for k, v in desired.items()):
        return "unchanged", before, after, None, "edit did not round-trip; left untouched"
    return action, before, after, new_text, None


# --------------------------------------------------------------------------- plan / apply

def _compute(target: ClientTarget, command: list[str], remove: bool, name: str = SERVER_NAME):
    if target.fmt == "codex-toml":
        return _compute_toml(target, command, remove, name)
    return _compute_json(target, command, remove, name)


def plan(clients: list[str] | None, command: list[str] = DEFAULT_COMMAND, remove: bool = False,
         home: Path | None = None, name: str = SERVER_NAME) -> list[PlannedChange]:
    """clients None = all detected. Never touches other keys/servers. Entry:
    JSON: {"command": cmd[0], "args": cmd[1:]} (claude also "type": "stdio").
    TOML: [mcp_servers.mail]\ncommand = "..."\nargs = [...]\nstartup_timeout_sec = 60"""
    command = list(command)
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise UsageError("name must be 1-64 characters: letters, digits, '-' or '_'")
    if not command or not all(isinstance(c, str) and c for c in command):
        raise UsageError("command must be a non-empty list of strings")
    all_targets = targets(home)
    by_key = {t.key: t for t in all_targets}
    if clients is None:
        chosen = [t for t in all_targets if t.detected]
        explicit = False
    else:
        unknown = [c for c in clients if c not in by_key]
        if unknown:
            raise UsageError(f"unknown client(s): {', '.join(unknown)}; valid: {', '.join(by_key)}")
        chosen = []
        for c in clients:
            if by_key[c] not in chosen:
                chosen.append(by_key[c])
        explicit = True
    changes = []
    for t in chosen:
        if explicit and not t.detected and not t.path.exists() and not remove:
            changes.append(PlannedChange(t, "unchanged", "(none)", "(none)",
                                         f"{t.name} was not detected on this machine; skipped", command, name))
            continue
        action, before, after, _text, error = _compute(t, command, remove, name)
        changes.append(PlannedChange(t, action, before, after, error, command, name))
    return changes


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        if path.exists():
            try:
                shutil.copymode(path, tmp)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(path: Path) -> Path | None:
    """One backup per file: <file>.bak-mailmcp (a previous backup is overwritten)."""
    if not path.exists():
        return None
    bak = path.with_name(f"{path.name}.bak-mailmcp")
    shutil.copy2(path, bak)
    return bak


def apply(changes: list[PlannedChange]) -> list[str]:
    """Backup each file to <file>.bak-mailmcp before writing; JSON written with indent=2
    preserving other content; TOML edited textually (append or replace only our table) and validated
    with tomllib after writing (restore backup on failure). Return human lines of what happened."""
    lines: list[str] = []
    for ch in changes:
        t = ch.target
        if ch.error:
            lines.append(f"{t.name}: skipped - {ch.error}")
            continue
        if ch.action == "unchanged":
            lines.append(f"{t.name}: already up to date ({t.path})")
            continue
        # Recompute from the file as it is right now (it may have changed since plan()).
        action, _b, _a, new_text, error = _compute(t, ch.command, ch.action == "remove", ch.name)
        if error:
            lines.append(f"{t.name}: skipped - {error}")
            continue
        if new_text is None:
            lines.append(f"{t.name}: already up to date ({t.path})")
            continue
        try:
            bak = _backup(t.path)
            _atomic_write(t.path, new_text)
        except OSError as e:
            lines.append(f"{t.name}: FAILED to write {t.path}: {e}")
            continue
        if t.fmt == "codex-toml":
            try:
                _mail_table(t.path.read_bytes().decode("utf-8-sig"), ch.name)
            except Exception:  # noqa: BLE001 - restore on any validation failure
                if bak is not None:
                    shutil.copy2(bak, t.path)
                else:
                    try:
                        t.path.unlink()
                    except OSError:
                        pass
                lines.append(f"{t.name}: written file failed TOML validation; restored original")
                continue
        verb = {"add": "added", "update": "updated", "remove": "removed"}[action]
        extra = f" (backup: {bak.name})" if bak else ""
        lines.append(f"{t.name}: {verb} '{ch.name}' in {t.path}{extra}")
        if t.key == "claude":
            lines.append(f"{t.name}: close {t.name} before installing if it is running, "
                         "it may overwrite the file.")
    return lines
