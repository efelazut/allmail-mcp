"""Shared fixtures: isolated config home, in-memory keyring, local IMAP/SMTP test servers."""
from __future__ import annotations

import asyncio
import re
import socket
import threading

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from mailmcp.config import Account


class MemoryKeyring(KeyringBackend):
    """Secure-looking in-memory keyring for tests."""

    priority = 5  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


@pytest.fixture
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def mailmcp_home(tmp_path, monkeypatch):
    """Every test gets its own config dir and never touches the network for autoconfig by default."""
    home = tmp_path / "mailmcp-home"
    monkeypatch.setenv("MAILMCP_HOME", str(home))
    monkeypatch.delenv("MAILMCP_NO_AUTOCONFIG", raising=False)
    monkeypatch.delenv("MAILMCP_ALLOW_PLAINTEXT_FOR_TESTS", raising=False)
    return home


@pytest.fixture
def make_account():
    def factory(**overrides) -> Account:
        values = dict(
            id="efe-gmail", email="efe@gmail.com", display_name="Efe Lazut", provider="gmail",
            imap_host="imap.gmail.com", imap_port=993, imap_security="ssl",
            smtp_host="smtp.gmail.com", smtp_port=465, smtp_security="ssl",
            username="efe@gmail.com", smtp_saves_sent=True,
        )
        values.update(overrides)
        return Account(**values)
    return factory


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ImapTestServer:
    """aioimaplib's MockImapServer on 127.0.0.1, run in a background thread (plaintext)."""

    def __init__(self) -> None:
        from aioimaplib.imap_testing_server import MockImapServer

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.server = MockImapServer(loop=self.loop)
        self.port = free_port()

        async def start():
            return await self.server.run_server(host="127.0.0.1", port=self.port)

        self._srv = asyncio.run_coroutine_threadsafe(start(), self.loop).result(10)

    def call(self, fn, *args, **kwargs):
        """Run fn on the server's event loop (server state is not thread-safe)."""
        fut = asyncio.run_coroutine_threadsafe(self._wrap(fn, *args, **kwargs), self.loop)
        return fut.result(10)

    @staticmethod
    async def _wrap(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def deliver(self, user: str, mail, mailbox: str = "INBOX") -> list[int]:
        return self.call(self.server.receive, mail, imap_user=user, mailbox=mailbox)

    @property
    def state(self):
        return self.server._server_state

    def close(self) -> None:
        def stop():
            self._srv.close()
            self.state.reset()
        self.call(stop)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)
        self.loop.close()


def _patched_list(special: dict[str, str]):
    """The mock's LIST mishandles quoted patterns and has no SPECIAL-USE flags; replace it."""
    def list_(self, tag, *args):
        pattern = args[1].strip('"')
        regex = re.compile(pattern.replace("*", ".*").replace("%", "[^/]*"))
        for name in sorted(self.server_state.mailboxes[self.user_login]):
            if regex.fullmatch(name):
                self.send_untagged_line('LIST (%s) "/" "%s"' % (special.get(name, ""), name))
        self.send_tagged_line(tag, "OK LIST completed.")
    return list_


@pytest.fixture
def imap_server(monkeypatch):
    from aioimaplib.imap_testing_server import ImapProtocol

    monkeypatch.setenv("MAILMCP_ALLOW_PLAINTEXT_FOR_TESTS", "1")
    special = {"Trash": r"\Trash", "Sent": r"\Sent", "Drafts": r"\Drafts"}
    monkeypatch.setattr(ImapProtocol, "list", _patched_list(special))
    orig_exec = ImapProtocol.exec_command

    def exec_command(self, tag, command_array):  # the mock does not understand quoted arguments
        return orig_exec(self, tag, [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in command_array])

    monkeypatch.setattr(ImapProtocol, "exec_command", exec_command)
    orig_range = ImapProtocol._build_sequence_range

    def build_range(self, pattern):  # MOVE of a single uid needs a range object, not a list
        got = orig_range(self, pattern)
        return range(got[0], got[0] + 1) if isinstance(got, list) else got

    monkeypatch.setattr(ImapProtocol, "_build_sequence_range", build_range)
    orig_examine = ImapProtocol.examine

    def examine(self, tag, *args):  # the mock forgets to remember the mailbox on EXAMINE (read-only select)
        self.user_mailbox = args[0]
        return orig_examine(self, tag, *args)

    monkeypatch.setattr(ImapProtocol, "examine", examine)

    def capability(self, tag, *args):  # the mock only reports a stub list; report what it really supports
        self.send_untagged_line("CAPABILITY IMAP4rev1 %s" % self.capabilities)
        self.send_tagged_line(tag, "OK CAPABILITY completed")

    monkeypatch.setattr(ImapProtocol, "capability", capability)
    server = ImapTestServer()
    server.special_use = special  # tests may mutate (e.g. clear) before connecting
    yield server
    server.close()


@pytest.fixture
def local_imap_account(make_account, imap_server):
    return make_account(
        id="local", email="user@example.test", username="user@example.test", provider="custom",
        imap_host="127.0.0.1", imap_port=imap_server.port, imap_security="plain", smtp_saves_sent=False,
    )
