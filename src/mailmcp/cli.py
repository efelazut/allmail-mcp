"""Command line entry point: `mailmcp`."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys

from . import __version__
from .errors import MailMcpError, UsageError

CLIENT_KEYS = ["claude", "codex", "cursor", "antigravity", "gemini"]


def _setup_streams() -> None:
    """Make ✓ ✗ and non-ASCII text safe on cp1252 consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - not a TextIOWrapper (tests, redirects)
            pass


def _setup_stderr_only() -> None:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def _out(msg: str = "") -> None:
    print(msg, flush=True)


def _err(msg: str = "") -> None:
    print(msg, file=sys.stderr, flush=True)


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # noqa: D401
        raise UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="allmail-mcp", description="All your mailboxes in any AI agent, over MCP.")
    p.add_argument("--version", action="store_true", help="print version and exit")
    sub = p.add_subparsers(dest="cmd", parser_class=_Parser)

    sub.add_parser("serve", help="run the MCP stdio server (default)")
    sub.add_parser("add-account", help="add a mail account through a local browser page")
    sub.add_parser("accounts", help="list configured accounts")
    ra = sub.add_parser("remove-account", help="delete an account and its stored password")
    ra.add_argument("id")
    ra.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")

    for name, helptext in (("install", "register mailmcp in MCP clients"),
                           ("uninstall", "remove mailmcp from MCP clients")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--client", action="append", choices=CLIENT_KEYS, dest="clients",
                        help="limit to a client (repeatable); default: all detected")
        sp.add_argument("--yes", "-y", action="store_true", help="apply without asking")
        sp.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
        sp.add_argument("--name", default="mail", help="server name in the client config (default: mail)")
        if name == "install":
            sp.add_argument("--command", default=None,
                            help='launch command, e.g. "uvx allmail-mcp" or \'["python","-m","mailmcp"]\'')
    sub.add_parser("doctor", help="check keyring, config and account logins")
    return p


def _parse_command(text: str | None) -> list[str]:
    from .install import DEFAULT_COMMAND
    if text is None or not text.strip():
        return list(DEFAULT_COMMAND)
    text = text.strip()
    if text.startswith("["):
        try:
            val = json.loads(text)
        except json.JSONDecodeError as e:
            raise UsageError(f"--command looks like JSON but is invalid: {e}") from None
        if not isinstance(val, list) or not val or not all(isinstance(x, str) and x for x in val):
            raise UsageError("--command JSON must be a non-empty array of strings")
        return val
    try:
        parts = shlex.split(text, posix=(os.name != "nt"))
    except ValueError as e:
        raise UsageError(f"cannot parse --command: {e}") from None
    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        cleaned.append(part)
    if not cleaned:
        raise UsageError("--command is empty")
    return cleaned


def _confirm(question: str) -> bool:
    try:
        ans = input(question)
    except EOFError:
        return False
    return ans.strip().lower() in ("y", "yes")


# --------------------------------------------------------------------------- commands

def _cmd_serve(_args) -> int:
    _setup_stderr_only()
    from .server import run
    run()
    return 0


def _cmd_add_account(_args) -> int:
    try:
        from .server import add_account_cli
    except ImportError:
        _err("add-account is not available in this build.")
        return 1
    return int(add_account_cli() or 0)


def _cmd_accounts(_args) -> int:
    from .config import load_config
    cfg = load_config()
    if not cfg.accounts:
        _out("No accounts yet. Run: mailmcp add-account")
        return 0
    rows = [("ID", "EMAIL", "PROVIDER", "IMAP HOST")]
    rows += [(a.id, a.email, a.provider, a.imap_host) for a in cfg.accounts.values()]
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    for r in rows:
        _out("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    return 0


def _cmd_remove_account(args) -> int:
    from . import secrets_store
    from .config import load_config, save_config
    cfg = load_config()
    acct = cfg.get(args.id)  # raises AccountNotFound
    if not args.yes and not _confirm(f"Remove account {acct.id} ({acct.email}) and its stored password? [y/N] "):
        _out("Cancelled.")
        return 0
    cfg.accounts.pop(acct.id, None)
    save_config(cfg)
    try:
        secrets_store.delete_password(acct.id)
    except MailMcpError as e:
        _err(f"Account removed from config, but the stored password could not be deleted: {e}")
        return 1
    _out(f"Removed {acct.id}.")
    return 0


def _print_plan(changes) -> None:
    for ch in changes:
        t = ch.target
        label = ch.action.upper() if not ch.error else "SKIP"
        _out(f"{t.name}  [{label}]  {t.path}")
        if ch.error:
            _out(f"  ! {ch.error}")
            continue
        if ch.action == "unchanged":
            _out("  = already up to date")
            continue
        if ch.before and ch.before != "(none)":
            for ln in ch.before.splitlines():
                _out(f"  - {ln}")
        if ch.after and ch.after != "(none)":
            for ln in ch.after.splitlines():
                _out(f"  + {ln}")


def _cmd_install(args, remove: bool = False) -> int:
    from . import install
    command = list(install.DEFAULT_COMMAND) if remove else _parse_command(getattr(args, "command", None))
    changes = install.plan(args.clients, command=command, remove=remove,
                          name=getattr(args, "name", "mail"))
    if not changes:
        _err("No supported MCP client detected. Use --client claude|codex|cursor|antigravity|gemini.")
        return 1
    _print_plan(changes)
    actionable = [c for c in changes if c.action != "unchanged" and not c.error]
    has_errors = any(c.error for c in changes)
    if args.dry_run:
        _out("\nDry run: nothing written.")
        return 0
    if not actionable:
        return 1 if has_errors else 0
    if not args.yes and not _confirm("\nApply? [y/N] "):
        _out("Cancelled; nothing written.")
        return 0
    _out("")
    for line in install.apply(changes):
        _out(line)
    if not remove:
        _out(f"\nRestart your MCP client to load the '{getattr(args, 'name', 'mail')}' server, then ask it to add an account.")
    return 1 if has_errors else 0


def _cmd_uninstall(args) -> int:
    return _cmd_install(args, remove=True)


def _cmd_doctor(_args) -> int:
    failures = 0

    def line(mark: str, text: str) -> None:
        _out(f"{mark} {text}")

    def ok(text: str) -> None:
        line("✓", text)

    def bad(text: str) -> None:
        nonlocal failures
        failures += 1
        line("✗", text)

    def na(text: str) -> None:
        line("-", f"{text}: not available")

    ok(f"allmail-mcp {__version__}")
    v = sys.version_info
    (ok if v >= (3, 10) else bad)(f"Python {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 10) else " (need 3.10+)"))

    try:
        from . import secrets_store
        secrets_store.assert_secure_backend()
        ok("Keyring backend is secure")
    except NotImplementedError:
        na("Keyring check")
    except MailMcpError as e:
        bad(f"Keyring: {e}")
    except Exception as e:  # noqa: BLE001
        bad(f"Keyring check failed ({type(e).__name__})")

    cfg = None
    try:
        from .config import config_dir, load_config
        cfg = load_config()
        ok(f"Config readable ({config_dir()}), {len(cfg.accounts)} account(s)")
    except NotImplementedError:
        na("Config")
    except MailMcpError as e:
        bad(f"Config: {e}")
    except Exception as e:  # noqa: BLE001
        bad(f"Config unreadable ({type(e).__name__})")

    for acct in (cfg.accounts.values() if cfg else []):
        password = None
        try:
            from . import secrets_store
            password = secrets_store.get_password(acct.id)
            ok(f"{acct.id}: password found in keyring")
        except NotImplementedError:
            na(f"{acct.id}: keyring password")
        except MailMcpError as e:
            bad(f"{acct.id}: {e}")
        except Exception as e:  # noqa: BLE001
            bad(f"{acct.id}: keyring read failed ({type(e).__name__})")
        if password is None:
            continue
        try:
            from .imap_backend import test_login
            from .providers import ServerSettings
            server = ServerSettings(
                provider=acct.provider, imap_host=acct.imap_host, imap_port=acct.imap_port,
                imap_security=acct.imap_security, smtp_host=acct.smtp_host, smtp_port=acct.smtp_port,
                smtp_security=acct.smtp_security, smtp_saves_sent=acct.smtp_saves_sent, source="manual")
            test_login(server, acct.username, password)
            ok(f"{acct.id}: IMAP login works ({acct.imap_host})")
        except NotImplementedError:
            na(f"{acct.id}: IMAP login")
        except MailMcpError as e:
            bad(f"{acct.id}: IMAP login failed: {e}")
        except Exception as e:  # noqa: BLE001
            bad(f"{acct.id}: IMAP login failed ({type(e).__name__})")
    return 1 if failures else 0


_COMMANDS = {
    "serve": _cmd_serve,
    "add-account": _cmd_add_account,
    "accounts": _cmd_accounts,
    "remove-account": _cmd_remove_account,
    "install": _cmd_install,
    "uninstall": _cmd_uninstall,
    "doctor": _cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    """mailmcp                -> run the MCP stdio server (same as `serve`)
    mailmcp serve            -> run the MCP stdio server
    mailmcp add-account      -> start local page, open browser, wait until added (prints account id)
    mailmcp accounts         -> list accounts (no secrets)
    mailmcp remove-account ID -> delete config entry + keyring password (asks y/N unless --yes)
    mailmcp install [--client claude|codex|cursor|antigravity|gemini ...] [--command "uvx allmail-mcp"] [--yes] [--dry-run]
    mailmcp uninstall [--client ...] [--yes]
    mailmcp doctor           -> check keyring backend, config, each account's IMAP login (no secrets printed)
    mailmcp --version
    Any output during `serve` must go to stderr (stdout is the MCP channel)."""
    raw = list(sys.argv[1:] if argv is None else argv)
    is_serve = not raw or raw[0] == "serve"
    if not is_serve:
        _setup_streams()
    try:
        try:
            args = _build_parser().parse_args(raw)
        except SystemExit as e:  # --help
            return int(e.code or 0)
        if args.version:
            _out(f"allmail-mcp {__version__}")
            return 0
        handler = _COMMANDS[args.cmd or "serve"]
        return int(handler(args) or 0)
    except UsageError as e:
        _err(f"mailmcp: {e}")
        return 2
    except MailMcpError as e:
        _err(str(e))
        return 1
    except KeyboardInterrupt:
        _err("Interrupted.")
        return 130
