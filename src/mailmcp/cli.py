"""Command line entry point: `mailmcp`."""
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    """mailmcp                -> run the MCP stdio server (same as `serve`)
    mailmcp serve            -> run the MCP stdio server
    mailmcp add-account      -> start local page, open browser, wait until added (prints account id)
    mailmcp accounts         -> list accounts (no secrets)
    mailmcp remove-account ID -> delete config entry + keyring password (asks y/N unless --yes)
    mailmcp install [--client claude|codex|cursor|antigravity|gemini ...] [--command "uvx mailmcp"] [--yes] [--dry-run]
    mailmcp uninstall [--client ...] [--yes]
    mailmcp doctor           -> check keyring backend, config, each account's IMAP login (no secrets printed)
    mailmcp --version
    Any output during `serve` must go to stderr (stdout is the MCP channel)."""
    raise NotImplementedError
