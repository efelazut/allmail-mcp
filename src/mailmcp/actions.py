"""Pending actions that only a human click can execute."""
from __future__ import annotations

import hmac
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import ActionNotPending, InvalidActionToken, MailMcpError


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

_KEEP_FINISHED_SECONDS = 3600


class ActionStore:
    """Thread-safe, in-memory. TTL default 15 minutes."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._actions: dict[str, PendingAction] = {}
        self._executors: dict[str, Executor] = {}

    def register_executor(self, kind: str, fn: Executor) -> None:
        with self._lock:
            self._executors[kind] = fn

    def create(self, kind: str, account_id: str | None, payload: dict, display: dict) -> PendingAction:
        now = time.time()
        with self._lock:
            self._prune(now)
            aid = secrets.token_hex(3)
            while aid in self._actions:
                aid = secrets.token_hex(3)
            action = PendingAction(
                id=aid, kind=kind, account_id=account_id, payload=payload, display=display,
                token=secrets.token_urlsafe(32), created_at=now, expires_at=now + self._ttl,
            )
            self._actions[aid] = action
            return action

    # -- internals (call with lock held) ---------------------------------
    def _prune(self, now: float) -> None:
        stale = [i for i, a in self._actions.items()
                 if a.status != "pending" and now > a.expires_at + _KEEP_FINISHED_SECONDS]
        for i in stale:
            del self._actions[i]

    def _refresh(self, action: PendingAction) -> None:
        if action.status == "pending" and time.time() > action.expires_at:
            action.status = "expired"
            action.result = "This request expired."

    # -- public ----------------------------------------------------------
    def get(self, action_id: str) -> PendingAction | None:
        """Marks expired actions as 'expired' on access."""
        with self._lock:
            a = self._actions.get(action_id)
            if a is not None:
                self._refresh(a)
            return a

    def token_matches(self, action_id: str, token: str) -> PendingAction | None:
        """Constant-time token check regardless of status (used to show status pages)."""
        with self._lock:
            a = self._actions.get(action_id)
            if a is None:
                return None
            self._refresh(a)
            if not isinstance(token, str) or not hmac.compare_digest(
                    a.token.encode(), token.encode("utf-8", "replace")):
                return None
            return a

    def check_token(self, action_id: str, token: str) -> PendingAction | None:
        """Constant-time compare; None if wrong/expired/not pending."""
        a = self.token_matches(action_id, token)
        if a is None or a.status != "pending":
            return None
        return a

    def _claim(self, action_id: str, token: str, new_status: str) -> tuple[PendingAction, Executor | None]:
        with self._lock:
            a = self._actions.get(action_id)
            if a is None:
                raise InvalidActionToken("Invalid or unknown approval link.")
            self._refresh(a)
            if not isinstance(token, str) or not hmac.compare_digest(
                    a.token.encode(), token.encode("utf-8", "replace")):
                raise InvalidActionToken("Invalid or unknown approval link.")
            if a.status != "pending":
                raise ActionNotPending(f"This request is already {a.status}.")
            a.status = new_status
            executor = self._executors.get(a.kind) if new_status == "approved" else None
            return a, executor

    def approve(self, action_id: str, token: str) -> PendingAction:
        """Validate token, set 'approved', run executor synchronously, set 'done'/'failed' + result.
        Token is consumed (second approve fails). Raise errors.MailMcpError if invalid."""
        action, executor = self._claim(action_id, token, "approved")
        if executor is None:
            status, result = "failed", f"No executor registered for '{action.kind}'."
        else:
            try:
                status, result = "done", executor(action) or "Done."
            except MailMcpError as e:
                status, result = "failed", str(e) or "Action failed."
            except Exception as e:  # noqa: BLE001 - never leak details to the page
                print(f"mailmcp: executor for {action.kind!r} crashed: {type(e).__name__}",
                      file=sys.stderr)
                status, result = "failed", "Unexpected error"
        with self._lock:
            action.status = status
            action.result = result
        return action

    def reject(self, action_id: str, token: str) -> PendingAction:
        action, _ = self._claim(action_id, token, "rejected")
        with self._lock:
            action.result = "Rejected by user."
        return action
