"""IMAP operations over imapclient. One short-lived connection per tool call."""
from __future__ import annotations

import functools
import imaplib
import os
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from imapclient import IMAPClient
from imapclient import exceptions as imap_exc

from .config import Account
from .errors import MailMcpError, MailServerError
from .providers import ServerSettings

# Bytes of each message fetched (BODY.PEEK[]<0.N>) to build a snippet. Never marks as read.
SNIPPET_FETCH_BYTES = 16384
SNIPPET_FETCH_ITEM = f"BODY.PEEK[]<0.{SNIPPET_FETCH_BYTES}>"
MAX_SEARCH_LIMIT = 200

_ZERO_WIDTH_RE = re.compile("[​-‏‪-‮⁠-⁤﻿]")
_WS_RE = re.compile(r"\s+")
_APPENDUID_RE = re.compile(r"APPENDUID\s+\d+\s+(\d+)", re.IGNORECASE)

_LOGIN_HINT = (
    "Login failed: check the app password; Gmail needs 2-Step Verification and an app "
    "password, iCloud/Yahoo/Yandex need an app-specific password, and IMAP must be enabled "
    "in the account's mail settings."
)

_SPECIAL_FLAGS = {
    "\\drafts": "\\Drafts", "\\sent": "\\Sent", "\\trash": "\\Trash", "\\junk": "\\Junk",
    "\\archive": "\\Archive", "\\all": "\\All",
}

# Casefolded fallback names per special-use (matched on the full name and the last path part).
_NAME_FALLBACKS: dict[str, tuple[str, ...]] = {
    "\\drafts": (
        "drafts", "draft", "inbox.drafts", "[gmail]/drafts", "[google mail]/drafts", "taslaklar",
        "taslak", "entwürfe", "brouillons", "borradores", "bozze", "черновики",
    ),
    "\\sent": (
        "sent", "sent items", "sent mail", "sent messages", "inbox.sent", "[gmail]/sent mail",
        "[google mail]/sent mail", "gönderilmiş öğeler", "gönderilmiş postalar", "gönderilen öğeler",
        "gönderilenler", "gesendet", "éléments envoyés", "enviados", "inviati", "отправленные",
    ),
    "\\trash": (
        "trash", "deleted items", "deleted messages", "bin", "inbox.trash", "[gmail]/trash",
        "[gmail]/bin", "[google mail]/trash", "çöp kutusu", "silinmiş öğeler", "silinen öğeler",
        "silinenler", "papierkorb", "gelöscht", "corbeille", "papelera", "cestino", "корзина",
        "удалённые",
    ),
    "\\junk": ("junk", "spam", "junk e-mail", "bulk mail", "[gmail]/spam", "gereksiz", "istenmeyen"),
    "\\archive": ("archive", "archives", "arşiv", "[gmail]/all mail"),
}


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


# --------------------------------------------------------------------------- helpers

def _plaintext_allowed() -> bool:
    """Plain (unencrypted) IMAP is accepted only for local tests."""
    return os.environ.get("MAILMCP_ALLOW_PLAINTEXT_FOR_TESTS") == "1"


def _scrub(text: str, password: str | None, limit: int = 200) -> str:
    text = _WS_RE.sub(" ", text).strip()
    if password:
        text = text.replace(password, "***")
    return text[:limit]


def _map_error(exc: BaseException, password: str | None = None, host: str = "the mail server") -> MailServerError:
    """Translate library/network errors into a MailServerError with a friendly hint (no secrets)."""
    if isinstance(exc, MailMcpError):
        return exc  # type: ignore[return-value]
    if isinstance(exc, imap_exc.LoginError):
        detail = _scrub(str(exc), password)
        return MailServerError(f"{_LOGIN_HINT} (server said: {detail})" if detail else _LOGIN_HINT)
    if isinstance(exc, ssl.SSLCertVerificationError):
        return MailServerError(
            f"TLS certificate for {host} could not be verified ({exc.verify_message}). "
            "Check the host name and your system clock.")
    if isinstance(exc, ssl.SSLError):
        return MailServerError(
            f"TLS error talking to {host} ({exc.reason or 'ssl error'}). Check the port and security setting "
            "(993 = ssl, 143 = starttls).")
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return MailServerError(f"Timed out talking to {host}. Check your connection and the server settings.")
    if isinstance(exc, socket.gaierror):
        return MailServerError(f"Cannot resolve {host}: check the host name and your internet connection.")
    if isinstance(exc, ConnectionRefusedError):
        return MailServerError(f"Connection to {host} was refused: check the host and port.")
    if isinstance(exc, (imap_exc.IMAPClientAbortError, imaplib.IMAP4.abort)):
        return MailServerError(f"The connection to {host} was dropped ({_scrub(str(exc), password)}). Try again.")
    if isinstance(exc, OSError):
        return MailServerError(f"Network error talking to {host}: {type(exc).__name__}.")
    if isinstance(exc, (imap_exc.IMAPClientError, imaplib.IMAP4.error)):
        text = _scrub(str(exc), password)
        low = text.lower()
        if "authenticationfailed" in low or "invalid credentials" in low or "login failed" in low:
            return MailServerError(f"{_LOGIN_HINT} (server said: {text})")
        if any(k in low for k in ("nonexistent", "doesn't exist", "does not exist", "unknown mailbox",
                                  "no such mailbox", "mailbox not found")):
            return MailServerError(f"Folder not found ({text}). Use folders_list to see valid folder names.")
        return MailServerError(f"IMAP error: {text}")
    return MailServerError(f"Unexpected mail server error: {type(exc).__name__}: {_scrub(str(exc), password)}")


def _connect(host: str, port: int, security: str, timeout: float) -> IMAPClient:
    """Open a TLS-verified IMAP connection (not yet logged in)."""
    if security == "ssl":
        return IMAPClient(host, port=port, ssl=True, ssl_context=ssl.create_default_context(), timeout=timeout)
    if security == "starttls":
        client = IMAPClient(host, port=port, ssl=False, timeout=timeout)
        try:
            client.starttls(ssl.create_default_context())
        except BaseException:
            _quiet_shutdown(client)
            raise
        return client
    if security == "plain" and _plaintext_allowed():
        return IMAPClient(host, port=port, ssl=False, timeout=timeout)
    raise MailServerError(f"Unsupported IMAP security mode {security!r}; use 'ssl' or 'starttls'.")


def _quiet_shutdown(client: IMAPClient) -> None:
    try:
        client.shutdown()
    except Exception:  # noqa: BLE001
        pass


def test_login(server: ServerSettings, username: str, password: str, timeout: float = 20) -> None:
    """Connect + LOGIN + LOGOUT. Raise errors.MailServerError with a friendly hint
    (wrong app password / IMAP disabled / 2FA required) on failure."""
    client = None
    try:
        client = _connect(server.imap_host, server.imap_port, server.imap_security, timeout)
        client.login(username, password)
        try:
            client.logout()
        except Exception:  # noqa: BLE001 - logout failure after a good login is harmless
            _quiet_shutdown(client)
    except MailServerError:
        raise
    except Exception as exc:  # noqa: BLE001
        if client is not None:
            _quiet_shutdown(client)
        raise _map_error(exc, password, server.imap_host) from None


test_login.__test__ = False  # not a pytest test, despite the name


def _decode_bytes(value: bytes | str | None) -> str:
    """Decode an ENVELOPE field (bytes, maybe RFC 2047 encoded) into a clean single-line str."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            text = value.decode("latin-1")
    else:
        text = value
    if "=?" in text:
        try:
            text = str(make_header(decode_header(text)))
        except Exception:  # noqa: BLE001 - malformed encoded-word: keep raw text
            pass
    return _WS_RE.sub(" ", _ZERO_WIDTH_RE.sub("", text)).strip()


def _fmt_address(name: str, addr: str) -> str:
    if not name:
        return addr
    if re.search(r'[()<>\[\]:;@\\,."]', name):
        name = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{name} <{addr}>" if addr else name


def _format_addresses(addrs) -> str:
    """Render imapclient Address tuples as 'Name <a@b>, ...' (skips group markers)."""
    out: list[str] = []
    for a in addrs or ():
        mailbox, host = _decode_bytes(a.mailbox), _decode_bytes(a.host)
        if not mailbox or not host:
            continue
        out.append(_fmt_address(_decode_bytes(a.name), f"{mailbox}@{host}"))
    return ", ".join(out)


def _collapse(text: str, n: int = 200) -> str:
    text = _WS_RE.sub(" ", _ZERO_WIDTH_RE.sub("", text)).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _flag_str(flag: bytes | str) -> str:
    return flag.decode("ascii", "replace") if isinstance(flag, bytes) else str(flag)


def _is_unread(flags) -> bool:
    return not any(_flag_str(f).lower() == "\\seen" for f in (flags or ()))


def _body_bytes(data: dict) -> bytes | None:
    """The BODY[] / BODY[]<0> / BODY.PEEK[] payload of a FETCH response, whatever key the server used."""
    for key, value in data.items():
        k = _flag_str(key).upper()
        if (k.startswith("BODY[") or k.startswith("BODY.PEEK[")) and isinstance(value, (bytes, bytearray)):
            return bytes(value)
    return None


def _has_attachment(structure) -> bool:
    """True if a BODYSTRUCTURE contains an 'attachment' disposition."""
    def walk(node) -> bool:
        if isinstance(node, (bytes, str)):
            return _flag_str(node).lower() == "attachment"
        if isinstance(node, (list, tuple)):
            return any(walk(x) for x in node)
        return False
    return walk(structure)


def _parse_bytes(raw: bytes | None) -> EmailMessage | None:
    if not raw:
        return None
    try:
        return BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        return None


def _html_to_text(html: str) -> str:
    from . import clean  # lazy: owned by another module

    return clean.html_to_text(html)


def _best_text(msg: Message) -> str:
    """text/plain if present, else cleaned HTML; '' when nothing decodable."""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))  # type: ignore[attr-defined]
        if part is None:
            return ""
        content = part.get_content()
        if part.get_content_subtype() == "html":
            return _html_to_text(content)
        return content
    except Exception:  # noqa: BLE001 - truncated/garbled parts are fine for snippets
        return ""


def _header(msg: Message | None, name: str) -> str:
    if msg is None:
        return ""
    try:
        return _decode_bytes(str(msg.get(name, "") or ""))
    except Exception:  # noqa: BLE001
        return ""


def _msg_date(msg: Message | None) -> datetime | None:
    try:
        raw = msg.get("Date") if msg is not None else None
        return parsedate_to_datetime(str(raw)) if raw else None
    except Exception:  # noqa: BLE001
        return None


def _guarded(func):
    """Map unexpected library errors in MailBox methods to MailServerError."""
    @functools.wraps(func)
    def wrapper(self: "MailBox", *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except MailMcpError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _map_error(exc, self._password, self._account.imap_host) from None
    return wrapper


# --------------------------------------------------------------------------- MailBox

class MailBox:
    """Usage: with MailBox(account, password) as mb: mb.search(...)"""

    def __init__(self, account: Account, password: str, timeout: float = 30) -> None:
        self._account = account
        self._password = password
        self._timeout = timeout
        self._client: IMAPClient | None = None
        self._folders: list[Folder] | None = None
        self._caps: set[str] | None = None

    def __enter__(self) -> "MailBox":
        acc = self._account
        client = None
        try:
            client = _connect(acc.imap_host, acc.imap_port, acc.imap_security, self._timeout)
            client.login(acc.username, self._password)
        except Exception as exc:  # noqa: BLE001
            if client is not None:
                _quiet_shutdown(client)
            raise _map_error(exc, self._password, acc.imap_host) from None
        self._client = client
        return self

    def __exit__(self, *exc) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            _quiet_shutdown(client)

    # -- internals

    def _c(self) -> IMAPClient:
        if self._client is None:
            raise MailServerError("Not connected: use MailBox as a context manager.")
        return self._client

    def _capabilities(self) -> set[str]:
        if self._caps is None:
            self._caps = {_flag_str(c).upper() for c in self._c().capabilities()}
        return self._caps

    def _select(self, folder: str, readonly: bool) -> None:
        self._c().select_folder(folder, readonly=readonly)

    # -- folders

    @_guarded
    def list_folders(self) -> list[Folder]:
        if self._folders is not None:
            return self._folders
        out: list[Folder] = []
        for flags, _delim, name in self._c().list_folders():
            flag_strs = [_flag_str(f) for f in flags]
            special = None
            for f in flag_strs:
                if f.lower() in _SPECIAL_FLAGS:
                    special = _SPECIAL_FLAGS[f.lower()]
                    break
            if name.upper() == "INBOX":
                special = "\\Inbox"
            out.append(Folder(name=name, special_use=special, flags=flag_strs))
        self._folders = out
        return out

    @_guarded
    def special_folder(self, use: str) -> str:
        """Return folder name for '\\Drafts' / '\\Sent' / '\\Trash' via SPECIAL-USE, else common names
        (Drafts, Draft, [Gmail]/Drafts, INBOX.Drafts, Taslaklar, Sent, Sent Items, Sent Messages,
        Trash, Deleted Items, Deleted Messages, Bin, Çöp Kutusu ...). Raise MailServerError if none."""
        key = use.lower() if use.startswith("\\") else "\\" + use.lower()
        folders = self.list_folders()
        selectable = [f for f in folders if "\\noselect" not in {x.lower() for x in f.flags}]
        for f in selectable:
            if f.special_use and f.special_use.lower() == key:
                return f.name
        names = _NAME_FALLBACKS.get(key, ())
        for f in selectable:
            full = f.name.casefold()
            leaf = re.split(r"[/.]", f.name)[-1].casefold()
            if full in names or leaf in names:
                return f.name
        raise MailServerError(
            f"Could not find the {key[1:].capitalize()} folder on this account. "
            "Use folders_list to see the available folders."
        )

    # -- reading

    @_guarded
    def search(self, folder: str = "INBOX", query: str | None = None, sender: str | None = None,
               subject: str | None = None, since: date | None = None, before: date | None = None,
               unread_only: bool = False, limit: int = 20) -> list[MessageSummary]:
        """Newest first. Uses X-GM-RAW for free-text query on Gmail, else IMAP SEARCH TEXT (UTF-8 charset).
        Fetch only ENVELOPE/FLAGS/BODYSTRUCTURE + a small BODY.PEEK snippet; never mark as read."""
        client = self._c()
        limit = max(0, min(int(limit), MAX_SEARCH_LIMIT))
        if limit == 0:
            return []
        self._select(folder, readonly=True)
        criteria = self._search_criteria(query, sender, subject, since, before, unread_only)
        needs_utf8 = any(isinstance(c, str) and not c.isascii() for c in criteria)
        uids = sorted(client.search(criteria, charset="UTF-8" if needs_utf8 else None), reverse=True)[:limit]
        if not uids:
            return []
        data = client.fetch(uids, ["ENVELOPE", "FLAGS", "BODYSTRUCTURE", SNIPPET_FETCH_ITEM])
        return [self._summary_from(folder, uid, data[uid]) for uid in uids if uid in data]

    def _search_criteria(self, query, sender, subject, since, before, unread_only) -> list:
        criteria: list = []
        if query:
            if "X-GM-EXT-1" in self._capabilities():
                criteria += ["X-GM-RAW", query]
            else:
                criteria += ["TEXT", query]
        if sender:
            criteria += ["FROM", sender]
        if subject:
            criteria += ["SUBJECT", subject]
        if since:
            criteria += ["SINCE", since]
        if before:
            criteria += ["BEFORE", before]
        if unread_only:
            criteria.append("UNSEEN")
        return criteria or ["ALL"]

    def _summary_from(self, folder: str, uid: int, data: dict) -> MessageSummary:
        parsed = _parse_bytes(_body_bytes(data))
        env = data.get(b"ENVELOPE")
        if env is not None:
            subject = _decode_bytes(env.subject)
            sender = _format_addresses(env.from_)
            to = _format_addresses(env.to)
            when = env.date
        else:  # server omitted ENVELOPE: fall back to the partial message headers
            subject, sender, to = _header(parsed, "Subject"), _header(parsed, "From"), _header(parsed, "To")
            when = _msg_date(parsed)
        raw = _body_bytes(data) or b""
        # A partial fetch cut inside the headers has no body at all; don't mistake header text for it.
        has_body = b"\r\n\r\n" in raw or b"\n\n" in raw
        text = _best_text(parsed) if parsed is not None and has_body else ""
        if b"BODYSTRUCTURE" in data:
            has_att = _has_attachment(data[b"BODYSTRUCTURE"])
        else:
            has_att = bool(parsed is not None and any(True for _ in parsed.iter_attachments()))
        return MessageSummary(
            account_id=self._account.id, folder=folder, uid=int(uid), date=when, sender=sender, to=to,
            subject=subject, snippet=_collapse(text), unread=_is_unread(data.get(b"FLAGS")),
            has_attachments=has_att,
        )

    @_guarded
    def fetch(self, folder: str, uid: int) -> ParsedMessage:
        """BODY.PEEK[] then parse with email.policy.default. Raise MailServerError if uid not found."""
        client = self._c()
        self._select(folder, readonly=True)
        data = client.fetch([uid], ["FLAGS", "BODY.PEEK[]"])
        item = data.get(uid)
        raw = _body_bytes(item) if item else None
        if raw is None:
            raise MailServerError(f"Message {uid} not found in folder {folder!r}.")
        msg = _parse_bytes(raw)
        if msg is None:
            raise MailServerError(f"Message {uid} in {folder!r} could not be parsed.")
        text = _best_text(msg)
        attachments: list[Attachment] = []
        for part in msg.iter_attachments():
            filename = part.get_filename() or ""
            if not filename and part.get_content_disposition() != "attachment":
                continue
            try:
                size = len(part.get_payload(decode=True) or b"") or len(bytes(part))
            except Exception:  # noqa: BLE001
                size = 0
            attachments.append(Attachment(_decode_bytes(filename), part.get_content_type(), size))
        refs = _header(msg, "References")
        summary = MessageSummary(
            account_id=self._account.id, folder=folder, uid=int(uid), date=_msg_date(msg),
            sender=_header(msg, "From"), to=_header(msg, "To"), subject=_header(msg, "Subject"),
            snippet=_collapse(text), unread=_is_unread(item.get(b"FLAGS")), has_attachments=bool(attachments),
        )
        return ParsedMessage(
            summary=summary, message_id=_header(msg, "Message-ID") or None, references=refs or None,
            cc=_header(msg, "Cc"), reply_to=_header(msg, "Reply-To"), text=text, attachments=attachments,
        )

    # -- writing

    def _append(self, use: str, msg: EmailMessage, flags: list[str]) -> int | None:
        folder = self.special_folder(use)
        response = self._c().append(folder, msg.as_bytes(), flags=flags)
        text = _flag_str(response) if response is not None else ""
        m = _APPENDUID_RE.search(text)
        return int(m.group(1)) if m else None

    @_guarded
    def append_draft(self, msg: EmailMessage) -> int | None:
        """APPEND to Drafts with \\Draft (and \\Seen). Return new UID if UIDPLUS gives it."""
        return self._append("\\Drafts", msg, ["\\Draft", "\\Seen"])

    @_guarded
    def append_sent(self, msg: EmailMessage) -> None:
        """APPEND to Sent with \\Seen (used when account.smtp_saves_sent is False)."""
        self._append("\\Sent", msg, ["\\Seen"])

    @_guarded
    def move_to_trash(self, folder: str, uids: list[int]) -> str:
        """Move to Trash (MOVE, else COPY + \\Deleted + UID EXPUNGE of only those uids). Return trash folder name.
        If folder already is Trash, do nothing and raise MailServerError (no permanent delete)."""
        if not uids:
            raise MailServerError("No messages given to move to Trash.")
        client = self._c()
        trash = self.special_folder("\\Trash")
        if folder.casefold() == trash.casefold():
            raise MailServerError(
                f"Those messages are already in {trash!r}; mailmcp never deletes mail permanently."
            )
        caps = self._capabilities()
        if "MOVE" not in caps and "UIDPLUS" not in caps:
            raise MailServerError(
                "This server supports neither MOVE nor UIDPLUS, so mailmcp cannot move messages to Trash "
                "safely (it will not expunge the whole folder). Delete them in your mail app instead."
            )
        self._select(folder, readonly=False)
        uid_list = [int(u) for u in uids]
        if "MOVE" in caps:
            client.move(uid_list, trash)
        else:
            client.copy(uid_list, trash)
            client.add_flags(uid_list, ["\\Deleted"])
            client.uid_expunge(uid_list)
        return trash
