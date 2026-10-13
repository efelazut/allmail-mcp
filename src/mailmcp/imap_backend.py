"""IMAP operations over imapclient. One short-lived connection per tool call."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage

from .config import Account
from .providers import ServerSettings


@dataclass
class Folder:
    name: str
    special_use: str | None     # "\Inbox" "\Drafts" "\Sent" "\Trash" "\Junk" "\Archive" "\All" or None
    flags: list[str] = field(default_factory=list)


@dataclass
class MessageSummary:
    account_id: str
    folder: str
    uid: int
    date: datetime | None
    sender: str
    to: str
    subject: str
    snippet: str            # plain text, <= ~200 chars, cleaned
    unread: bool
    has_attachments: bool


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int


@dataclass
class ParsedMessage:
    summary: MessageSummary
    message_id: str | None
    references: str | None
    cc: str
    reply_to: str
    text: str               # best text body (text/plain, else cleaned HTML)
    attachments: list[Attachment]


def test_login(server: ServerSettings, username: str, password: str, timeout: float = 20) -> None:
    """Connect + LOGIN + LOGOUT. Raise errors.MailServerError with a friendly hint
    (wrong app password / IMAP disabled / 2FA required) on failure."""
    raise NotImplementedError


class MailBox:
    """Usage: with MailBox(account, password) as mb: mb.search(...)"""

    def __init__(self, account: Account, password: str, timeout: float = 30) -> None:
        raise NotImplementedError

    def __enter__(self) -> "MailBox":
        raise NotImplementedError

    def __exit__(self, *exc) -> None:
        raise NotImplementedError

    def list_folders(self) -> list[Folder]:
        raise NotImplementedError

    def special_folder(self, use: str) -> str:
        """Return folder name for '\Drafts' / '\Sent' / '\Trash' via SPECIAL-USE, else common names
        (Drafts, Draft, [Gmail]/Drafts, INBOX.Drafts, Taslaklar, Sent, Sent Items, Sent Messages,
        Trash, Deleted Items, Deleted Messages, Bin, Çöp Kutusu ...). Raise MailServerError if none."""
        raise NotImplementedError

    def search(self, folder: str = "INBOX", query: str | None = None, sender: str | None = None,
               subject: str | None = None, since: date | None = None, before: date | None = None,
               unread_only: bool = False, limit: int = 20) -> list[MessageSummary]:
        """Newest first. Uses X-GM-RAW for free-text query on Gmail, else IMAP SEARCH TEXT (UTF-8 charset).
        Fetch only ENVELOPE/FLAGS/BODYSTRUCTURE + a small BODY.PEEK snippet; never mark as read."""
        raise NotImplementedError

    def fetch(self, folder: str, uid: int) -> ParsedMessage:
        """BODY.PEEK[] then parse with email.policy.default. Raise MailServerError if uid not found."""
        raise NotImplementedError

    def append_draft(self, msg: EmailMessage) -> int | None:
        """APPEND to Drafts with \Draft (and \Seen). Return new UID if UIDPLUS gives it."""
        raise NotImplementedError

    def append_sent(self, msg: EmailMessage) -> None:
        """APPEND to Sent with \Seen (used when account.smtp_saves_sent is False)."""
        raise NotImplementedError

    def move_to_trash(self, folder: str, uids: list[int]) -> str:
        """Move to Trash (MOVE, else COPY + \Deleted + UID EXPUNGE of only those uids). Return trash folder name.
        If folder already is Trash, do nothing and raise MailServerError (no permanent delete)."""
        raise NotImplementedError
