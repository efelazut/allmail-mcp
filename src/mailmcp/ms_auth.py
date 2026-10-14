"""Microsoft (Outlook.com / Hotmail / Live) sign-in for IMAP and SMTP via OAuth 2.0.

The user signs in on Microsoft's own page in their default browser (MSAL interactive flow with a
localhost redirect); mailmcp never sees the Microsoft password. Tokens live in an MSAL cache file
under config_dir(), encrypted with a key kept in the OS keyring (refresh tokens are too long for
some keyrings, e.g. Windows Credential Manager).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from .config import config_dir
from .errors import MailMcpError, SecretStoreError
from .secrets_store import get_password, set_password

# Public client id of the allmail-mcp app registration ("Personal Microsoft accounts", redirect
# http://localhost). Override with env MAILMCP_MS_CLIENT_ID to use your own registration.
DEFAULT_CLIENT_ID = "6f09cfb8-7e11-4033-b11c-5bd23c5c2d45"
AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["https://outlook.office.com/IMAP.AccessAsUser.All", "https://outlook.office.com/SMTP.Send"]
_KEY_ID = "__ms_token_cache_key__"
_CACHE_FILE = "ms_tokens.bin"
_lock = threading.Lock()


class MicrosoftAuthError(MailMcpError):
    pass


def client_id() -> str:
    cid = (os.environ.get("MAILMCP_MS_CLIENT_ID") or DEFAULT_CLIENT_ID).strip()
    if not cid:
        raise MicrosoftAuthError(
            "Outlook/Hotmail sign-in is not configured in this build: set MAILMCP_MS_CLIENT_ID to the "
            "client id of a Microsoft app registration (see docs/MICROSOFT.md).")
    return cid


def _fernet():
    from cryptography.fernet import Fernet

    try:
        key = get_password(_KEY_ID)
    except SecretStoreError:
        key = None
    if not key:
        key = Fernet.generate_key().decode()
        set_password(_KEY_ID, key)
    return Fernet(key.encode())


def _cache_path() -> Path:
    return config_dir() / _CACHE_FILE


def _load_cache():
    import msal
    from cryptography.fernet import InvalidToken

    cache = msal.SerializableTokenCache()
    path = _cache_path()
    if path.exists():
        try:
            cache.deserialize(_fernet().decrypt(path.read_bytes()).decode("utf-8"))
        except (InvalidToken, ValueError):
            pass  # unreadable cache (e.g. key lost): the user simply signs in again
    return cache


def _save_cache(cache) -> None:
    if not cache.has_state_changed:
        return
    path = _cache_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_fernet().encrypt(cache.serialize().encode("utf-8")))
    os.replace(tmp, path)


def _app(cache):
    import msal

    return msal.PublicClientApplication(client_id(), authority=AUTHORITY, token_cache=cache)


def _error_text(result: dict) -> str:
    code = str(result.get("error") or "unknown_error")
    desc = str(result.get("error_description") or "").split("\n")[0][:200]
    return f"{code}: {desc}" if desc else code


def sign_in(email: str, timeout: int = 300) -> str:
    """Open Microsoft's sign-in page in the default browser and wait for the user.
    Return the signed-in account's address (what IMAP/SMTP use as the username)."""
    with _lock:
        cache = _load_cache()
        app = _app(cache)
        result = app.acquire_token_interactive(
            SCOPES, login_hint=email, prompt="select_account", timeout=timeout,
            success_template="<h1>Signed in. You can close this tab and return to allmail-mcp.</h1>")
        if "access_token" not in result:
            raise MicrosoftAuthError(f"Microsoft sign-in did not complete ({_error_text(result)}).")
        _save_cache(cache)
        claims = result.get("id_token_claims") or {}
        return str(claims.get("preferred_username") or claims.get("email") or email)


def access_token(username: str) -> str:
    """A fresh access token for this account from the cached refresh token (no browser)."""
    with _lock:
        cache = _load_cache()
        app = _app(cache)
        accounts = [a for a in app.get_accounts() if a.get("username", "").lower() == username.lower()]
        result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        if not result or "access_token" not in result:
            raise MicrosoftAuthError(
                f"The Microsoft sign-in for {username} has expired or was revoked. Remove the account "
                f"and add it again (mailmcp remove-account, then add-account).")
        _save_cache(cache)
        return str(result["access_token"])


def sign_out(username: str) -> None:
    """Forget cached tokens for this account (used by remove-account)."""
    try:
        cid = client_id()
    except MicrosoftAuthError:
        return
    del cid
    with _lock:
        cache = _load_cache()
        app = _app(cache)
        for acc in app.get_accounts():
            if acc.get("username", "").lower() == username.lower():
                app.remove_account(acc)
        _save_cache(cache)
