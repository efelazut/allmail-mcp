"""OS keyring wrapper. Service name: 'mailmcp', username: account id."""
from __future__ import annotations

SERVICE = "mailmcp"


def assert_secure_backend() -> None:
    """Raise errors.SecretStoreError if the active keyring backend is a fail/null/plaintext backend.
    Message must explain how to fix (e.g. install a Secret Service on headless Linux)."""
    raise NotImplementedError


def set_password(account_id: str, password: str) -> None:
    raise NotImplementedError


def get_password(account_id: str) -> str:
    """Raise errors.SecretStoreError('No stored password for <id>; run account_add again') if missing."""
    raise NotImplementedError


def delete_password(account_id: str) -> None:
    """Ignore if already missing."""
    raise NotImplementedError
