"""Pending actions that only a human click can execute."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PendingAction:
    id: str                     # short, e.g. 'a7f3k2' (not secret)
    kind: str                   # 'send' | 'trash' | 'settings'
    account_id: str | None
    payload: dict[str, Any]     # data the executor needs (server-side only)
    display: dict[str, Any]     # what the approval page shows (built server-side from payload)
    token: str                  # secret, single use, in the approval URL
    created_at: float
    expires_at: float
    status: str = "pending"     # pending | approved | done | failed | rejected | expired
    result: str | None = None   # human-readable outcome or error (no secrets)
    meta: dict[str, Any] = field(default_factory=dict)


Executor = Callable[[PendingAction], str]   # returns result text; raises MailMcpError on failure


class ActionStore:
    """Thread-safe, in-memory. TTL default 15 minutes."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        raise NotImplementedError

    def register_executor(self, kind: str, fn: Executor) -> None:
        raise NotImplementedError

    def create(self, kind: str, account_id: str | None, payload: dict, display: dict) -> PendingAction:
        raise NotImplementedError

    def get(self, action_id: str) -> PendingAction | None:
        """Marks expired actions as 'expired' on access."""
        raise NotImplementedError

    def check_token(self, action_id: str, token: str) -> PendingAction | None:
        """Constant-time compare; None if wrong/expired/not pending."""
        raise NotImplementedError

    def approve(self, action_id: str, token: str) -> PendingAction:
        """Validate token, set 'approved', run executor synchronously, set 'done'/'failed' + result.
        Token is consumed (second approve fails). Raise errors.MailMcpError if invalid."""
        raise NotImplementedError

    def reject(self, action_id: str, token: str) -> PendingAction:
        raise NotImplementedError
