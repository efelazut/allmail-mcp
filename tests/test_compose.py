import pytest

from mailmcp import compose
from mailmcp.errors import ComposeError
from mailmcp.imap_backend import MessageSummary, ParsedMessage


def _parent(subject="Toplantı notları", message_id="<abc@mail.example>", references="<r1@x> <r2@x>"):
    summary = MessageSummary("a", "INBOX", 7, None, "x@y.com", "efe@gmail.com", subject, "", False, False)
    return ParsedMessage(summary, message_id, references, "", "", "text", [])


def test_parse_recipients_string_and_list():
    assert compose.parse_recipients("a@x.com, B <b@y.com>") == ["a@x.com", "B <b@y.com>"]
    assert compose.parse_recipients(["a@x.com", "C <c@z.org>"]) == ["a@x.com", "C <c@z.org>"]
    assert compose.parse_recipients(None) == []
    assert compose.parse_recipients("") == []


def test_parse_recipients_quotes_names_with_commas():
    assert compose.parse_recipients('"Lazut, Efe" <e@x.com>') == ['"Lazut, Efe" <e@x.com>']


def test_parse_recipients_keeps_unicode_name():
    assert compose.parse_recipients("Çağrı Şen <c@x.com>") == ["Çağrı Şen <c@x.com>"]


def test_parse_recipients_idn_domain_punycoded():
    assert compose.parse_recipients("a@bücher.example") == ["a@xn--bcher-kva.example"]


@pytest.mark.parametrize("bad", [
    "not-an-address", "a@", "@x.com", "a b@x.com", "a@@x.com", "a@x..com", "a@x.com\r\nBcc: evil@y.com",
    "a@x.com\nX: y", "<>", "a@.com",
])
def test_parse_recipients_rejects_invalid(bad):
    with pytest.raises(ComposeError):
        compose.parse_recipients(bad)


def test_parse_recipients_rejects_crlf_in_list_item():
    with pytest.raises(ComposeError):
        compose.parse_recipients(["ok@x.com", "bad@x.com\r\nBcc: z@z.com"])


def test_build_basic(make_account):
    msg = compose.build_message(make_account(), "a@x.com", "Merhaba", "Gövde ğüşiöç\nİkinci satır")
    assert str(msg["From"]) == "Efe Lazut <efe@gmail.com>"
    assert str(msg["To"]) == "a@x.com"
    assert msg["Date"] and msg["Message-ID"]
    assert str(msg["Message-ID"]).endswith("@gmail.com>")
    assert msg.get_content_type() == "text/plain"
    assert msg.get_content_charset() == "utf-8"
    assert "ğüşiöç" in msg.get_content()
    # round trip through bytes keeps everything intact
    from email import message_from_bytes, policy
    back = message_from_bytes(msg.as_bytes(), policy=policy.default)
    assert back["Subject"] == "Merhaba" and "İkinci satır" in back.get_content()


def test_display_name_with_specials_is_quoted(make_account):
    msg = compose.build_message(make_account(display_name='Lazut, "Efe"'), "a@x.com", "s", "b")
    assert str(msg["From"]).startswith('"Lazut, \\"Efe\\"" <efe@gmail.com>')


def test_unicode_subject_roundtrips(make_account):
    msg = compose.build_message(make_account(), "a@x.com", "Çarşamba toplantısı", "b")
    from email import message_from_bytes, policy
    assert message_from_bytes(msg.as_bytes(), policy=policy.default)["Subject"] == "Çarşamba toplantısı"


@pytest.mark.parametrize("subject", ["hi\r\nBcc: evil@x.com", "hi\nthere", "a\rb", "x\x00y"])
def test_subject_header_injection_rejected(make_account, subject):
    with pytest.raises(ComposeError):
        compose.build_message(make_account(), "a@x.com", subject, "b")


def test_requires_a_recipient(make_account):
    with pytest.raises(ComposeError, match="recipient"):
        compose.build_message(make_account(), [], "s", "b")
    # bcc-only is allowed
    msg = compose.build_message(make_account(), None, "s", "b", bcc="h@x.com")
    assert msg["Bcc"] == "h@x.com" and msg["To"] is None


def test_cc_bcc_headers(make_account):
    msg = compose.build_message(make_account(), "a@x.com", "s", "b", cc=["c@x.com", "d@x.com"], bcc="h@x.com")
    assert str(msg["Cc"]) == "c@x.com, d@x.com"
    d = compose.describe(msg)
    assert d == {"from": "Efe Lazut <efe@gmail.com>", "to": "a@x.com", "cc": "c@x.com, d@x.com",
                 "bcc": "h@x.com", "subject": "s", "body": "b\n"}


def test_reply_threading(make_account):
    msg = compose.build_message(make_account(), "x@y.com", "", "cevap", reply_to=_parent())
    assert str(msg["Subject"]) == "Re: Toplantı notları"
    assert str(msg["In-Reply-To"]) == "<abc@mail.example>"
    assert str(msg["References"]) == "<r1@x> <r2@x> <abc@mail.example>"


def test_reply_subject_not_double_prefixed(make_account):
    msg = compose.build_message(make_account(), "x@y.com", "", "b", reply_to=_parent(subject="RE: Plan"))
    assert str(msg["Subject"]) == "RE: Plan"
    msg = compose.build_message(make_account(), "x@y.com", "Başka konu", "b", reply_to=_parent())
    assert str(msg["Subject"]) == "Re: Başka konu"


def test_reply_without_message_id_or_references(make_account):
    msg = compose.build_message(make_account(), "x@y.com", "", "b",
                                reply_to=_parent(message_id=None, references=None))
    assert msg["In-Reply-To"] is None and msg["References"] is None


def test_reply_ids_from_untrusted_mail_are_sanitized(make_account):
    evil = _parent(message_id="<ok@x>\r\nBcc: evil@z.com", references="<a@x>\r\nX-Evil: 1 <b@x>")
    msg = compose.build_message(make_account(), "x@y.com", "", "b", reply_to=evil)
    raw = msg.as_bytes().decode()
    assert "evil@z.com" not in raw and "X-Evil" not in raw
    assert str(msg["In-Reply-To"]) == "<ok@x>"
    assert str(msg["References"]) == "<a@x> <b@x> <ok@x>"


def test_message_id_uses_account_domain(make_account):
    acc = make_account(email="efe@kendi-domain.com.tr")
    msg = compose.build_message(acc, "a@x.com", "s", "b")
    assert str(msg["Message-ID"]).endswith("@kendi-domain.com.tr>")
