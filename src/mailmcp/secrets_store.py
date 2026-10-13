"""OS keyring wrapper. Service name: 'mailmcp', username: account id."""
from __future__ import annotations

import keyring
from keyring.backends import chainer
from keyring.errors import KeyringError, PasswordDeleteError

from .errors import SecretStoreError

SERVICE = "mailmcp"

_FIX_HINT = (
    "mailmcp stores passwords only in the OS keyring (macOS Keychain, Windows Credential "
    "Locker, or a Secret Service such as GNOME Keyring / KWallet). On headless Linux install "
    "and unlock one (e.g. `sudo apt install gnome-keyring`, started inside a D-Bus session). "
    "Plaintext fallbacks are never used."
)


def _backend_problem(backend: object) -> str | None:
    """Return a reason string if `backend` is unacceptable, else None."""
    cls = type(backend)
    module = cls.__module__ or ""
    full = f"{module}.{cls.__qualname__}"
    if "keyrings.alt" in module:
        return f"{full} stores secrets in plaintext or weakly encrypted files"
    if module.startswith("keyring.backends.fail"):
        return "no keyring backend is available"
    if module.startswith("keyring.backends.null"):
        return "the null keyring backend discards secrets"
    if isinstance(backend, chainer.ChainerBackend):
        children = list(getattr(backend, "backends", []) or [])
        if not any(_backend_problem(b) is None for b in children):
            return "no usable keyring backend is available"
        return None
    try:
        priority = backend.priority  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - priority raises when the backend is unusable
        return f"{full} is not usable on this system"
    if priority < 1:
        return f"{full} has too low a priority to be a secure backend"
    return None


def assert_secure_backend() -> None:
    """Raise errors.SecretStoreError if the active keyring backend is a fail/null/plaintext backend.
    Message must explain how to fix (e.g. install a Secret Service on headless Linux)."""
    problem = _backend_problem(keyring.get_keyring())
    if problem:
        raise SecretStoreError(f"No secure keyring available: {problem}. {_FIX_HINT}")


def set_password(account_id: str, password: str) -> None:
    assert_secure_backend()
    try:
        keyring.set_password(SERVICE, account_id, password)
    except KeyringError as exc:
        raise SecretStoreError(
            f"Could not store the password in the OS keyring ({type(exc).__name__})."
        ) from exc


def get_password(account_id: str) -> str:
    """Raise errors.SecretStoreError('No stored password for <id>; run account_add again') if missing."""
    assert_secure_backend()
    try:
        value = keyring.get_password(SERVICE, account_id)
    except KeyringError as exc:
        raise SecretStoreError(
            f"Could not read the password from the OS keyring ({type(exc).__name__})."
        ) from exc
    if value is None:
        raise SecretStoreError(f"No stored password for {account_id}; run account_add again")
    return value


def delete_password(account_id: str) -> None:
    """Ignore if already missing."""
    assert_secure_backend()
    try:
        keyring.delete_password(SERVICE, account_id)
    except PasswordDeleteError:
        pass
    except KeyringError as exc:
        raise SecretStoreError(
            f"Could not delete the password from the OS keyring ({type(exc).__name__})."
        ) from exc
