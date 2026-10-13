"""Build outgoing messages."""
from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid

from .config import Account
from .errors import ComposeError
from .imap_backend import ParsedMessage

_CTL_RE = re.compile(r"[\x00-\x1f\x7f]")
_BAD_ADDR_CHARS = re.compile(r"[\s<>(),;:\\\"\[\]]")
_MSGID_RE = re.compile(r"<[^<>\s]+>")
_NAME_SPECIALS = re.compile(r"[()<>\[\]:;@\\,.\"]")


def _format_address(name: str, addr: str) -> str:
    """'Name <addr>' (name quoted when needed, kept as unicode) or bare 'addr'."""
    name = name.strip()
    if not name:
        return addr
    if _NAME_SPECIALS.search(name):
        name = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{name} <{addr}>"


def _check_addr(addr: str) -> str:
    local, sep, domain = addr.rpartition("@")
    if (not sep or not local or not domain or "@" in local or _BAD_ADDR_CHARS.search(addr)
            or _CTL_RE.search(addr) or domain.startswith(".") or domain.endswith(".")
            or ".." in domain):
        raise ComposeError(f"Invalid email address: {addr!r}")
    try:
        domain.encode("ascii")
    except UnicodeEncodeError:
        try:
            domain = domain.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ComposeError(f"Invalid email address domain: {addr!r}") from exc
    try:
        local.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ComposeError(f"Non-ASCII local parts are not supported: {addr!r}") from exc
    return f"{local}@{domain}"


def parse_recipients(value: str | list[str] | None) -> list[str]:
    """Accept 'a@x.com, B <b@y.com>' or a list. Validate each address (has one @, no spaces/CRLF in addr).
    Raise errors.ComposeError on invalid. Return normalized 'Name <addr>' / 'addr' strings."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ComposeError("Recipients must be strings")
        if "\r" in item or "\n" in item or "\x00" in item:
            raise ComposeError("Line breaks are not allowed in recipients")
        if not item.strip():
            continue
        parsed = getaddresses([item])
        if not parsed:
            raise ComposeError(f"Invalid email address: {item!r}")
        for name, addr in parsed:
            if not addr:
                raise ComposeError(f"Invalid email address: {item!r}")
            out.append(_format_address(name, _check_addr(addr.strip())))
    return out


def _clean_msgid(value: str | None) -> str | None:
    if not value:
        return None
    m = _MSGID_RE.search(value)
    return m.group(0) if m else None


def build_message(account: Account, to: str | list[str], subject: str, body: str,
                  cc: str | list[str] | None = None, bcc: str | list[str] | None = None,
                  reply_to: ParsedMessage | None = None) -> EmailMessage:
    """From = '"display_name" <email>'. Plain-text UTF-8 body. Date + Message-ID (make_msgid with account domain).
    When reply_to: subject gets 'Re: ' unless already present, In-Reply-To + References set.
    Reject CR/LF in subject (header injection). At least one recipient required."""
    subject = subject or ""
    if _CTL_RE.search(subject.replace("\t", " ")):
        raise ComposeError("Control characters or line breaks are not allowed in the subject")
    to_l, cc_l, bcc_l = parse_recipients(to), parse_recipients(cc), parse_recipients(bcc)
    if not (to_l or cc_l or bcc_l):
        raise ComposeError("At least one recipient is required")
    if _CTL_RE.search(account.display_name or ""):
        raise ComposeError("Invalid sender display name")
    from_addr = _check_addr(account.email)

    msg = EmailMessage()
    msg["From"] = _format_address(account.display_name or "", from_addr)
    if to_l:
        msg["To"] = ", ".join(to_l)
    if cc_l:
        msg["Cc"] = ", ".join(cc_l)
    if bcc_l:
        msg["Bcc"] = ", ".join(bcc_l)

    if reply_to is not None:
        subject = subject if subject.strip() else (reply_to.summary.subject or "")
        if _CTL_RE.search(subject.replace("\t", " ")):
            raise ComposeError("Control characters or line breaks are not allowed in the subject")
        if not re.match(r"\s*re\s*:", subject, re.IGNORECASE):
            subject = f"Re: {subject}".rstrip()
        parent_id = _clean_msgid(reply_to.message_id)
        if parent_id:
            msg["In-Reply-To"] = parent_id
            refs = _MSGID_RE.findall(reply_to.references or "")
            if parent_id not in refs:
                refs.append(parent_id)
            msg["References"] = " ".join(refs)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.rpartition("@")[2])
    msg.set_content(body or "", charset="utf-8")
    return msg


def _text_body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    try:
        return part.get_content()
    except Exception:  # noqa: BLE001 - best effort for display
        return ""


def describe(msg: EmailMessage) -> dict:
    """{'from','to','cc','bcc','subject','body'} for approval pages and tool output."""
    return {
        "from": str(msg.get("From", "")),
        "to": str(msg.get("To", "")),
        "cc": str(msg.get("Cc", "")),
        "bcc": str(msg.get("Bcc", "")),
        "subject": str(msg.get("Subject", "")),
        "body": _text_body(msg),
    }
