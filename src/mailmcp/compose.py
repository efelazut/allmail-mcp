"""Build outgoing messages."""
from __future__ import annotations

from email.message import EmailMessage

from .config import Account
from .imap_backend import ParsedMessage


def parse_recipients(value: str | list[str] | None) -> list[str]:
    """Accept 'a@x.com, B <b@y.com>' or a list. Validate each address (has one @, no spaces/CRLF in addr).
    Raise errors.ComposeError on invalid. Return normalized 'Name <addr>' / 'addr' strings."""
    raise NotImplementedError


def build_message(account: Account, to: str | list[str], subject: str, body: str,
                  cc: str | list[str] | None = None, bcc: str | list[str] | None = None,
                  reply_to: ParsedMessage | None = None) -> EmailMessage:
    """From = '"display_name" <email>'. Plain-text UTF-8 body. Date + Message-ID (make_msgid with account domain).
    When reply_to: subject gets 'Re: ' unless already present, In-Reply-To + References set.
    Reject CR/LF in subject (header injection). At least one recipient required."""
    raise NotImplementedError


def describe(msg: EmailMessage) -> dict:
    """{'from','to','cc','bcc','subject','body'} for approval pages and tool output."""
    raise NotImplementedError
