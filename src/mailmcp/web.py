"""Local web UI on 127.0.0.1: approval pages and the add-account page."""
from __future__ import annotations

from typing import Callable

from .actions import ActionStore

# Called by the add-account page after the user submits the form.
# Receives (email, password, display_name, manual_settings_or_None) and returns the new account id
# or raises errors.MailMcpError with a friendly message to show on the page.
AddAccountHandler = Callable[[str, str, str, dict | None], str]

# Called by the add-account page (GET /add/lookup?email=) to prefill server settings and help text.
LookupHandler = Callable[[str], dict]


class LocalWeb:
    def __init__(self, store: ActionStore, add_account: AddAccountHandler, lookup: LookupHandler,
                 host: str = "127.0.0.1", port: int = 0) -> None:
        raise NotImplementedError

    def start(self) -> None:
        """Idempotent; ThreadingHTTPServer in a daemon thread. Port 0 = random free port."""
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    @property
    def base_url(self) -> str:
        """'http://127.0.0.1:<port>' (starts the server if needed)."""
        raise NotImplementedError

    def approval_url(self, action_id: str) -> str:
        """base_url + '/a/<id>?t=<token>'."""
        raise NotImplementedError

    def new_add_account_url(self) -> str:
        """Create a single-use add-account session token (30 min) and return base_url + '/add?t=<token>'."""
        raise NotImplementedError

    def wait_for_add(self, timeout: float) -> str | None:
        """Block until an account is added via the page (returns its id) or timeout (None). Used by CLI."""
        raise NotImplementedError


def open_in_browser(url: str) -> bool:
    """webbrowser.open in a background thread; return False if no browser available (never raise)."""
    raise NotImplementedError
