"""Local web UI on 127.0.0.1: approval pages and the add-account page.

Security model (see docs/ARCHITECTURE.md rule 7): bound to loopback, Host header pinned
(DNS-rebinding defence), POSTs need a valid secret token + same Origin (required) + form
content type, strict CSP, no JavaScript anywhere, everything HTML-escaped.
"""
from __future__ import annotations

import hmac
import html
import http.server
import queue
import re
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import Callable

from .actions import ActionStore, PendingAction
from .errors import ActionNotPending, InvalidActionToken, MailMcpError

# Called by the add-account page after the user submits the form.
# Receives (email, password, display_name, manual_settings_or_None) and returns the new account id
# or raises errors.MailMcpError with a friendly message to show on the page.
AddAccountHandler = Callable[[str, str, str, dict | None], str]

# Called by the add-account page (GET /add?email=) to prefill server settings and help text.
LookupHandler = Callable[[str], dict]

MAX_BODY = 64 * 1024
ADD_SESSION_SECONDS = 30 * 60

CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")

_ID_RE = re.compile(r"^/a/([A-Za-z0-9_-]{1,64})$")

# --------------------------------------------------------------------- strings
_T = {
    "en": {
        "lang": "en",
        "approve": "Approve", "reject": "Reject",
        "send_title": "Approve sending this email?",
        "send_warn": "Nothing has been sent yet. Check the recipients and the text below. "
                     "Clicking Approve sends this exact message.",
        "from": "From", "to": "To", "cc": "Cc", "bcc": "Bcc (hidden recipients)",
        "subject": "Subject", "body": "Message",
        "trash_title": "Approve moving these messages to Trash?",
        "trash_warn": "The messages are moved to the Trash folder (not permanently deleted).",
        "account": "Account", "folder": "Folder", "date": "Date", "messages": "Messages",
        "settings_title": "Approve changing a safety setting?",
        "settings_warn": "This LOOSENS a protection: after approval your AI agent can act "
                         "without asking you first.",
        "setting": "Setting", "change": "Change", "on": "on (approval required)",
        "off": "off (no approval)",
        "generic_title": "Approve this action?",
        "done_title": "Done ✓", "done_hint": "You can close this tab.",
        "failed_title": "Failed", "failed_hint": "Nothing was changed unless stated below.",
        "rejected_title": "Rejected", "rejected_hint": "Nothing was done. You can close this tab.",
        "expired_title": "Expired", "expired_hint": "This request expired. Ask your AI agent to create a new one.",
        "status_title": "Request status", "status": "Status",
        "pending_title": "Pending",
        "forbidden_title": "Link not valid",
        "forbidden_text": "This link is invalid, expired or was already used.",
        "notfound_title": "Not found", "notfound_text": "Nothing here.",
        "badreq_title": "Bad request", "badreq_text": "The request was rejected.",
        "conflict_title": "Cannot complete",
        "add_title": "Add a mail account",
        "add_intro": "Your password is typed here, verified with the mail server and stored in your "
                     "operating system keyring. It never goes through the AI chat.",
        "lookup_label": "Which email address do you want to connect?",
        "lookup_btn": "Continue",
        "add_step": "Step 2: add your account",
        "connect_title": "Connect {email}",
        "change_email": "Use a different address",
        "why_app_pw": "{provider} does not let apps use your normal password. Instead you create a "
                      "code just for this app. It takes about a minute.",
        "s1": "Open the {provider} app password page",
        "s1_btn": "Create app password ↗",
        "s1_hint": "Give it any name (e.g. allmail-mcp) and press Create. It opens in a new tab.",
        "s2": "Paste the code {provider} shows you",
        "s2_ph": "xxxx xxxx xxxx xxxx",
        "s3_btn": "Connect",
        "more": "More options (name, server settings)",
        "ms_why": "Microsoft accounts connect with a normal sign-in: a Microsoft page opens in your "
                  "browser, you pick or sign in to the account, and you are done. No app password.",
        "ms_btn": "Sign in with Microsoft",
        "ms_hint": "After clicking, finish the sign-in in the new browser tab, then come back here.",
        "setting_labels": {"send_approval": "Approval before sending",
                           "trash_approval": "Approval before moving to Trash"},
        "email": "Email address", "display_name": "Display name",
        "password": "App password", "password_hint": "Use an app-specific password, not your normal login password.",
        "app_pw_link": "Create an app password for this provider",
        "app_pw_text": "Most providers require an app password (needs 2-step verification):",
        "advanced": "Advanced server settings (optional)",
        "advanced_hint": "Leave empty to detect automatically.",
        "imap_host": "IMAP host", "imap_port": "IMAP port", "imap_security": "IMAP security",
        "smtp_host": "SMTP host", "smtp_port": "SMTP port", "smtp_security": "SMTP security",
        "username": "Username (if not the email)",
        "add_btn": "Verify and add account",
        "added_title": "Account added ✓",
        "added_text": "Account {id} was added. Return to your AI agent.",
        "err_email": "Please enter a valid email address.",
        "err_password": "Please enter the password.",
        "err_port": "Ports must be numbers.",
        "err_security": "Security must be ssl or starttls.",
        "err_generic": "Unexpected error while adding the account.",
        "err_lookup": "Could not look up settings.",
        "found_provider": "Detected provider",
    },
    "tr": {
        "lang": "tr",
        "approve": "Onayla", "reject": "Reddet",
        "send_title": "Bu e-postanın gönderilmesini onaylıyor musun?",
        "send_warn": "Henüz hiçbir şey gönderilmedi. Alıcıları ve metni kontrol et. "
                     "Onayla'ya tıklamak bu mesajı aynen gönderir.",
        "from": "Kimden", "to": "Kime", "cc": "Bilgi (Cc)", "bcc": "Gizli alıcılar (Bcc)",
        "subject": "Konu", "body": "Mesaj",
        "trash_title": "Bu iletilerin çöp kutusuna taşınmasını onaylıyor musun?",
        "trash_warn": "İletiler çöp kutusuna taşınır (kalıcı olarak silinmez).",
        "account": "Hesap", "folder": "Klasör", "date": "Tarih", "messages": "İletiler",
        "settings_title": "Bir güvenlik ayarının değişmesini onaylıyor musun?",
        "settings_warn": "Bu bir korumayı GEVŞETİR: onaydan sonra yapay zekâ ajanın "
                         "sana sormadan işlem yapabilir.",
        "setting": "Ayar", "change": "Değişiklik", "on": "açık (onay gerekir)",
        "off": "kapalı (onay yok)",
        "generic_title": "Bu işlemi onaylıyor musun?",
        "done_title": "Tamamlandı ✓", "done_hint": "Bu sekmeyi kapatabilirsin.",
        "failed_title": "Başarısız", "failed_hint": "Aşağıda belirtilmedikçe hiçbir şey değişmedi.",
        "rejected_title": "Reddedildi", "rejected_hint": "Hiçbir şey yapılmadı. Bu sekmeyi kapatabilirsin.",
        "expired_title": "Süresi doldu", "expired_hint": "Bu isteğin süresi doldu. Ajanından yenisini iste.",
        "status_title": "İstek durumu", "status": "Durum",
        "pending_title": "Beklemede",
        "forbidden_title": "Bağlantı geçersiz",
        "forbidden_text": "Bu bağlantı geçersiz, süresi dolmuş veya daha önce kullanılmış.",
        "notfound_title": "Bulunamadı", "notfound_text": "Burada bir şey yok.",
        "badreq_title": "Hatalı istek", "badreq_text": "İstek reddedildi.",
        "conflict_title": "Tamamlanamadı",
        "add_title": "Posta hesabı ekle",
        "add_intro": "Şifren burada yazılır, posta sunucusuyla doğrulanır ve işletim sisteminin "
                     "anahtarlığında saklanır. Yapay zekâ sohbetinden asla geçmez.",
        "lookup_label": "Hangi e-posta adresini bağlamak istiyorsun?",
        "lookup_btn": "Devam",
        "add_step": "2. adım: hesabını ekle",
        "connect_title": "{email} adresini bağla",
        "change_email": "Başka bir adres kullan",
        "why_app_pw": "{provider}, uygulamaların normal şifreni kullanmasına izin vermez. Bunun yerine "
                      "yalnız bu uygulama için bir kod oluşturursun. Yaklaşık bir dakika sürer.",
        "s1": "{provider} uygulama şifresi sayfasını aç",
        "s1_btn": "Uygulama şifresi oluştur ↗",
        "s1_hint": "Herhangi bir ad ver (ör. allmail-mcp) ve Oluştur'a bas. Yeni sekmede açılır.",
        "s2": "{provider} sana bir kod gösterecek, onu buraya yapıştır",
        "s2_ph": "xxxx xxxx xxxx xxxx",
        "s3_btn": "Bağlan",
        "more": "Diğer seçenekler (ad, sunucu ayarları)",
        "ms_why": "Microsoft hesapları normal girişle bağlanır: tarayıcında Microsoft sayfası açılır, "
                  "hesabını seçer ya da giriş yaparsın, bu kadar. Uygulama şifresi yok.",
        "ms_btn": "Microsoft ile giriş yap",
        "ms_hint": "Tıkladıktan sonra yeni sekmede girişi bitir, sonra buraya dön.",
        "setting_labels": {"send_approval": "Göndermeden önce onay",
                           "trash_approval": "Çöp kutusuna taşımadan önce onay"},
        "email": "E-posta adresi", "display_name": "Görünen ad",
        "password": "Uygulama şifresi", "password_hint": "Normal giriş şifren değil, uygulamaya özel şifre kullan.",
        "app_pw_link": "Bu sağlayıcı için uygulama şifresi oluştur",
        "app_pw_text": "Çoğu sağlayıcı uygulama şifresi ister (2 adımlı doğrulama gerekir):",
        "advanced": "Gelişmiş sunucu ayarları (isteğe bağlı)",
        "advanced_hint": "Otomatik bulunması için boş bırak.",
        "imap_host": "IMAP sunucusu", "imap_port": "IMAP portu", "imap_security": "IMAP güvenliği",
        "smtp_host": "SMTP sunucusu", "smtp_port": "SMTP portu", "smtp_security": "SMTP güvenliği",
        "username": "Kullanıcı adı (e-posta değilse)",
        "add_btn": "Doğrula ve hesabı ekle",
        "added_title": "Hesap eklendi ✓",
        "added_text": "{id} hesabı eklendi. Yapay zekâ ajanına dönebilirsin.",
        "err_email": "Geçerli bir e-posta adresi gir.",
        "err_password": "Şifreyi gir.",
        "err_port": "Portlar sayı olmalı.",
        "err_security": "Güvenlik ssl veya starttls olmalı.",
        "err_generic": "Hesap eklenirken beklenmeyen bir hata oluştu.",
        "err_lookup": "Ayarlar bulunamadı.",
        "found_provider": "Bulunan sağlayıcı",
    },
}

_CSS = """
:root{color-scheme:light dark;--bg:#f4f5f7;--card:#fff;--fg:#1b1f24;--muted:#5b6570;--line:#d5dae0;
--ok:#1a7f37;--okfg:#fff;--bad:#c62828;--badfg:#fff;--warn:#fff4d6;--warnfg:#5c4300;--warnline:#e5c04a;
--code:#f0f2f5;--accent:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#14171a;--card:#1d2125;--fg:#e8eaed;--muted:#a0a8b0;
--line:#3a4148;--ok:#2ea043;--bad:#e5484d;--warn:#3b3114;--warnfg:#f3dc8f;--warnline:#7a6420;
--code:#262b30;--accent:#7aa2ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding:24px 16px}
main{max-width:640px;margin:0 auto;background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:24px}
h1{font-size:1.35rem;margin:0 0 12px}
p{margin:8px 0}
.muted{color:var(--muted);font-size:.9rem}
.warn{background:var(--warn);color:var(--warnfg);border:1px solid var(--warnline);border-radius:8px;
padding:10px 12px;margin:12px 0}
.err{background:#fde8e8;color:#7a1212;border:1px solid #e5a3a3;border-radius:8px;padding:10px 12px;margin:12px 0}
@media (prefers-color-scheme:dark){.err{background:#3a1a1a;color:#ffb4b4;border-color:#7a3030}}
table.kv{width:100%;border-collapse:collapse;margin:12px 0}
table.kv th{text-align:left;vertical-align:top;white-space:nowrap;padding:6px 12px 6px 0;color:var(--muted);
font-weight:600;width:1%}
table.kv td{padding:6px 0;word-break:break-word}
.rcpt{font-weight:700;font-size:1.05rem}
.bcc{color:var(--bad)}
.body{white-space:pre-wrap;word-break:break-word;background:var(--code);border:1px solid var(--line);
border-radius:8px;padding:12px;margin:8px 0 16px;max-height:420px;overflow:auto;font-family:inherit}
table.list{width:100%;border-collapse:collapse;margin:8px 0 16px;font-size:.92rem}
table.list th,table.list td{text-align:left;border-bottom:1px solid var(--line);padding:6px 8px 6px 0;
word-break:break-word}
.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.actions form{margin:0;flex:1 1 200px}
button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:12px 18px;cursor:pointer;width:100%}
button.ok{background:var(--ok);color:var(--okfg)}
button.bad{background:var(--bad);color:var(--badfg)}
button.neutral{background:var(--code);color:var(--fg);border:1px solid var(--line);width:auto}
button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
label{display:block;font-weight:600;margin:12px 0 4px}
input[type=text],input[type=email],input[type=password],input[type=number],select{width:100%;font:inherit;
padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
fieldset{border:1px solid var(--line);border-radius:8px;margin:16px 0;padding:8px 14px 14px}
legend{font-weight:600;padding:0 6px}
.row{display:flex;gap:12px;flex-wrap:wrap}.row>div{flex:1 1 140px}
a{color:var(--accent)}
.sep{border:0;border-top:1px solid var(--line);margin:20px 0}
ol.steps{list-style:none;counter-reset:s;padding:0;margin:16px 0}
ol.steps>li{counter-increment:s;position:relative;padding:0 0 18px 44px}
ol.steps>li::before{content:counter(s);position:absolute;left:0;top:0;width:30px;height:30px;border-radius:50%;
background:var(--accent);color:var(--card);font-weight:700;display:flex;align-items:center;justify-content:center}
.stitle{font-weight:700;margin:2px 0 8px;display:block}
a.btn{display:inline-block;background:var(--accent);color:var(--card);text-decoration:none;font-weight:600;
border-radius:8px;padding:10px 16px}
input.code{font-size:1.2rem;letter-spacing:.08em;font-family:ui-monospace,Consolas,monospace}
details{margin:12px 0}summary{cursor:pointer;color:var(--muted)}
"""

# --------------------------------------------------------------------- helpers


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pick_lang(accept: str | None) -> str:
    """'tr' if the highest-q language is Turkish, else 'en'."""
    best, best_q = "en", -1.0
    for part in (accept or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(";")
        tag = bits[0].strip().lower()
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if q > best_q:
            best_q = q
            best = "tr" if tag.split("-")[0] == "tr" else "en"
    return best


def _page(t: dict, title: str, inner: str) -> bytes:
    doc = (f'<!doctype html><html lang="{t["lang"]}"><head><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width,initial-scale=1">'
           '<meta name="referrer" content="same-origin">'
           f"<title>{_e(title)} — allmail-mcp</title><style>{_CSS}</style></head>"
           f"<body><main>{inner}</main></body></html>")
    return doc.encode("utf-8")


def _join(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _kv_row(label: str, value: str, cls: str = "") -> str:
    if "rcpt" in cls.split():  # isolate each address so direction overrides cannot reorder the line
        parts = [p.strip() for p in value.split(",") if p.strip()]
        cell = ", ".join(f'<bdi style="unicode-bidi:isolate">{_e(p)}</bdi>' for p in parts)
    else:
        cell = _e(value)
    return f'<tr><th>{_e(label)}</th><td class="{cls}">{cell}</td></tr>'


def _fmt_val(t: dict, value) -> str:
    if value is True:
        return t["on"]
    if value is False:
        return t["off"]
    return _join(value)


def _approval_buttons(t: dict, action_id: str, token: str) -> str:
    def form(act: str, cls: str, label: str) -> str:
        return (f'<form method="post" action="/a/{_e(action_id)}">'
                f'<input type="hidden" name="t" value="{_e(token)}">'
                f'<input type="hidden" name="action" value="{act}">'
                f'<button class="{cls}" type="submit">{_e(label)}</button></form>')
    return ('<div class="actions">' + form("approve", "ok", t["approve"])
            + form("reject", "bad", t["reject"]) + "</div>")


def _render_approval(t: dict, a: PendingAction) -> bytes:
    d = a.display or {}
    if a.kind == "send":
        rows = [_kv_row(t["from"], _join(d.get("from"))),
                _kv_row(t["to"], _join(d.get("to")), "rcpt")]
        if _join(d.get("cc")):
            rows.append(_kv_row(t["cc"], _join(d.get("cc")), "rcpt"))
        if _join(d.get("bcc")):
            rows.append(_kv_row(t["bcc"], _join(d.get("bcc")), "rcpt bcc"))
        rows.append(_kv_row(t["subject"], _join(d.get("subject"))))
        inner = (f'<h1>{_e(t["send_title"])}</h1><div class="warn">{_e(t["send_warn"])}</div>'
                 f'<table class="kv">{"".join(rows)}</table>'
                 f'<div class="muted">{_e(t["body"])}</div>'
                 f'<div class="body">{_e(d.get("body", ""))}</div>')
        title = t["send_title"]
    elif a.kind == "trash":
        msgs = d.get("messages") or []
        trs = "".join(
            f"<tr><td>{_e(m.get('date', ''))}</td><td>{_e(m.get('from', m.get('sender', '')))}</td>"
            f"<td>{_e(m.get('subject', ''))}</td></tr>" if isinstance(m, dict)
            else f"<tr><td colspan=3>{_e(m)}</td></tr>" for m in msgs)
        head = (f'<tr><th>{_e(t["date"])}</th><th>{_e(t["from"])}</th><th>{_e(t["subject"])}</th></tr>')
        rows = [_kv_row(t["account"], _join(d.get("account") or a.account_id)),
                _kv_row(t["folder"], _join(d.get("folder")))]
        inner = (f'<h1>{_e(t["trash_title"])}</h1><div class="warn">{_e(t["trash_warn"])}</div>'
                 f'<table class="kv">{"".join(rows)}</table>'
                 f'<div class="muted">{_e(t["messages"])} ({len(msgs)})</div>'
                 f'<table class="list">{head}{trs}</table>')
        title = t["trash_title"]
    elif a.kind == "settings":
        changes = d.get("changes")
        if not isinstance(changes, list):
            if "setting" in d:
                changes = [d]
            else:  # unknown shape: show every key
                changes = [{"setting": k, "to": v} for k, v in d.items()]
        rows = []
        for c in changes:
            if not isinstance(c, dict):
                rows.append(_kv_row(t["setting"], _join(c)))
                continue
            frm = c.get("from", c.get("old"))
            to = c.get("to", c.get("new"))
            text = (f"{_fmt_val(t, frm)} → {_fmt_val(t, to)}" if frm is not None
                    else _fmt_val(t, to))
            key = str(c.get("setting", c.get("name", t["setting"])))
            rows.append(_kv_row(t["setting_labels"].get(key, key), text))
        inner = (f'<h1>{_e(t["settings_title"])}</h1><div class="warn">{_e(t["settings_warn"])}</div>'
                 f'<table class="kv">{"".join(rows)}</table>')
        title = t["settings_title"]
    else:
        rows = [_kv_row(str(k), _fmt_val(t, v)) for k, v in d.items()]
        inner = f'<h1>{_e(t["generic_title"])}</h1><table class="kv">{"".join(rows)}</table>'
        title = t["generic_title"]
    inner += _approval_buttons(t, a.id, a.token)
    return _page(t, title, inner)


def _render_status(t: dict, a: PendingAction) -> bytes:
    key = {"done": "done", "failed": "failed", "rejected": "rejected", "expired": "expired"}.get(a.status)
    if key is None:
        title, hint = t["pending_title"], ""
        if a.status == "approved":
            title = t["status_title"]
    else:
        title, hint = t[key + "_title"], t[key + "_hint"]
    inner = f"<h1>{_e(title)}</h1>"
    if hint:
        inner += f"<p>{_e(hint)}</p>"
    if a.result:
        inner += f'<div class="body">{_e(a.result)}</div>'
    inner += f'<p class="muted">{_e(t["status"])}: {_e(a.status)}</p>'
    return _page(t, title, inner)


def _render_message(t: dict, title: str, text: str) -> bytes:
    return _page(t, title, f"<h1>{_e(title)}</h1><p>{_e(text)}</p>")


class _AddForm:
    FIELDS = ("email", "display_name", "imap_host", "imap_port", "imap_security",
              "smtp_host", "smtp_port", "smtp_security", "username")


_PROVIDER_NAMES = {"gmail": "Google", "icloud": "Apple", "yandex": "Yandex", "zoho": "Zoho"}


def _render_add(t: dict, token: str, values: dict, error: str | None = None,
                info: dict | None = None) -> bytes:
    v = {k: values.get(k, "") for k in _AddForm.FIELDS}
    tok = f'<input type="hidden" name="t" value="{_e(token)}">'
    looked_up = bool(info) and not info.get("error")
    if not looked_up and not error:
        # Screen 1: only ask for the address (GET; never carries the password).
        parts = [f'<h1>{_e(t["add_title"])}</h1><p class="muted">{_e(t["add_intro"])}</p>']
        if info and info.get("error"):
            parts.append(f'<div class="err">{_e(info["error"])}</div>')
        parts.append(
            f'<form method="get" action="/add"><label for="lk">{_e(t["lookup_label"])}</label>{tok}'
            f'<input id="lk" type="email" name="email" required value="{_e(v["email"])}" '
            f'autocomplete="off" placeholder="name@example.com" autofocus>'
            f'<div class="actions"><button class="ok" type="submit">{_e(t["lookup_btn"])}</button></div></form>')
        return _page(t, t["add_title"], "".join(parts))

    # Screen 2: provider-specific numbered steps.
    info = info if looked_up else {}
    if info.get("auth") == "oauth2":
        parts = [f'<h1>{_e(t["connect_title"].format(email=v["email"]))}</h1>',
                 f'<p class="muted"><a href="/add?t={_e(token)}">{_e(t["change_email"])}</a></p>',
                 f'<p>{_e(t["ms_why"])}</p>']
        if error:
            parts.append(f'<div class="err" role="alert">{_e(error)}</div>')
        parts.append(
            f'<form method="post" action="/add/microsoft" autocomplete="off">{tok}'
            f'<input type="hidden" name="email" value="{_e(v["email"])}">'
            f'<div class="actions"><button class="ok" type="submit">{_e(t["ms_btn"])}</button></div>'
            f'<p class="muted">{_e(t["ms_hint"])}</p>'
            f'<details><summary>{_e(t["more"])}</summary>'
            f'<label for="display_name">{_e(t["display_name"])}</label>'
            f'<input id="display_name" type="text" name="display_name" value="{_e(v["display_name"])}">'
            f"</details></form>")
        return _page(t, t["add_title"], "".join(parts))
    prov_key = str(info.get("provider") or "")
    prov = _PROVIDER_NAMES.get(prov_key, prov_key.capitalize() or "Mail")
    url = str(info.get("app_password_url") or "")
    has_url = url.lower().startswith(("https://", "http://"))
    parts = [f'<h1>{_e(t["connect_title"].format(email=v["email"]))}</h1>',
             f'<p class="muted"><a href="/add?t={_e(token)}">{_e(t["change_email"])}</a></p>']
    if prov_key:
        parts.append(f'<p class="muted">{_e(t["found_provider"])}: <b>{_e(prov_key)}</b></p>')
    parts.append(f'<p>{_e(t["why_app_pw"].format(provider=prov))}</p>')
    note = (info.get("notes_tr") if t["lang"] == "tr" else None) or info.get("notes")
    if note:
        parts.append(f'<div class="warn">{_e(note)}</div>')
    if error:
        parts.append(f'<div class="err" role="alert">{_e(error)}</div>')

    def sec(name: str) -> str:
        cur = v[name] or "ssl"
        opts = "".join(f'<option value="{o}"{" selected" if cur == o else ""}>{o}</option>'
                       for o in ("ssl", "starttls"))
        return f'<select name="{name}" id="{name}">{opts}</select>'

    steps = []
    if has_url:
        steps.append(f'<li><p class="stitle">{_e(t["s1"].format(provider=prov))}</p>'
                     f'<a class="btn" href="{_e(url)}" target="_blank" rel="noopener noreferrer">'
                     f'{_e(t["s1_btn"])}</a><p class="muted">{_e(t["s1_hint"])}</p></li>')
    steps.append(f'<li><label class="stitle" for="password">{_e(t["s2"].format(provider=prov))}</label>'
                 f'<input id="password" class="code" type="password" name="password" required '
                 f'autocomplete="off" placeholder="{_e(t["s2_ph"])}"></li>')
    steps.append(f'<li><button class="ok" type="submit">{_e(t["s3_btn"])}</button></li>')
    open_more = "" if prov_key else " open"
    parts.append(
        f'<form method="post" action="/add" autocomplete="off">{tok}'
        f'<input type="hidden" name="email" value="{_e(v["email"])}">'
        f'<ol class="steps">{"".join(steps)}</ol>'
        f'<details{open_more}><summary>{_e(t["more"])}</summary>'
        f'<label for="display_name">{_e(t["display_name"])}</label>'
        f'<input id="display_name" type="text" name="display_name" value="{_e(v["display_name"])}">'
        f'<p class="muted">{_e(t["advanced_hint"])}</p>'
        f'<div class="row"><div><label for="imap_host">{_e(t["imap_host"])}</label>'
        f'<input id="imap_host" type="text" name="imap_host" value="{_e(v["imap_host"])}"></div>'
        f'<div><label for="imap_port">{_e(t["imap_port"])}</label>'
        f'<input id="imap_port" type="text" inputmode="numeric" name="imap_port" value="{_e(v["imap_port"])}"></div>'
        f'<div><label for="imap_security">{_e(t["imap_security"])}</label>{sec("imap_security")}</div></div>'
        f'<div class="row"><div><label for="smtp_host">{_e(t["smtp_host"])}</label>'
        f'<input id="smtp_host" type="text" name="smtp_host" value="{_e(v["smtp_host"])}"></div>'
        f'<div><label for="smtp_port">{_e(t["smtp_port"])}</label>'
        f'<input id="smtp_port" type="text" inputmode="numeric" name="smtp_port" value="{_e(v["smtp_port"])}"></div>'
        f'<div><label for="smtp_security">{_e(t["smtp_security"])}</label>{sec("smtp_security")}</div></div>'
        f'<label for="username">{_e(t["username"])}</label>'
        f'<input id="username" type="text" name="username" autocomplete="off" value="{_e(v["username"])}">'
        f"</details></form>")
    return _page(t, t["add_title"], "".join(parts))


# --------------------------------------------------------------------- server


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    web: "LocalWeb"


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "mailmcp"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    timeout = 15

    def log_message(self, format, *args):  # noqa: A002 - silence (tokens are in URLs)
        pass

    # -- plumbing ---------------------------------------------------------
    @property
    def web(self) -> "LocalWeb":
        return self.server.web  # type: ignore[attr-defined]

    def _t(self) -> dict:
        return _T[_pick_lang(self.headers.get("Accept-Language"))]

    def _drain_unread_body(self) -> None:
        """Read a small unread request body before replying. Closing a socket with unread data makes
        Windows send a TCP reset, and the client then loses our error response."""
        if self.command != "POST" or getattr(self, "_body_done", False):
            return
        self._body_done = True
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < length <= 1024 * 1024:
            try:
                self.rfile.read(length)
            except OSError:
                pass

    def _send(self, status: int, body: bytes) -> None:
        self._drain_unread_body()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")  # "no-referrer" makes browsers send Origin: null on POST
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _msg(self, status: int, key: str) -> None:
        t = self._t()
        self._send(status, _render_message(t, t[key + "_title"], t[key + "_text"]))

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.web.port
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _origin_ok(self) -> bool:
        """Browsers always send Origin on form POSTs: a missing Origin is refused."""
        origin = self.headers.get("Origin")
        if origin is None:
            return False
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site.strip().lower() != "same-origin":
            return False
        port = self.web.port
        return origin.strip().lower() in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def _read_form(self) -> dict[str, str] | None:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            self._msg(400, "badreq")
            return None
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._msg(400, "badreq")
            return None
        if length < 0 or length > MAX_BODY:
            if 0 < length <= 1024 * 1024:  # drain so the client sees the 413, not a reset
                self.rfile.read(length)
            self._body_done = True
            self.send_response(413)
            self.send_header("Connection", "close")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        raw = self.rfile.read(length)
        self._body_done = True
        try:
            parsed = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True,
                                           max_num_fields=60)
        except (UnicodeDecodeError, ValueError):
            self._msg(400, "badreq")
            return None
        return {k: v[0] for k, v in parsed.items() if v}

    # -- verbs ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        try:
            if not self._host_ok():
                return self._msg(400, "badreq")
            url = urllib.parse.urlsplit(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items() if v}
            m = _ID_RE.match(url.path)
            if m:
                return self._get_action(m.group(1), q.get("t", ""))
            if url.path == "/add":
                return self._get_add(q)
            self._msg(404, "notfound")
        except Exception as e:  # noqa: BLE001
            print(f"mailmcp web: GET error {type(e).__name__}", file=sys.stderr)
            self._safe_500()

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not self._host_ok():
                return self._msg(400, "badreq")
            if not self._origin_ok():
                return self._msg(403, "forbidden")
            url = urllib.parse.urlsplit(self.path)
            m = _ID_RE.match(url.path)
            if not m and url.path not in ("/add", "/add/microsoft"):
                return self._msg(404, "notfound")
            form = self._read_form()
            if form is None:
                return
            if m:
                return self._post_action(m.group(1), form)
            if url.path == "/add/microsoft":
                return self._post_add_microsoft(form)
            return self._post_add(form)
        except Exception as e:  # noqa: BLE001
            print(f"mailmcp web: POST error {type(e).__name__}", file=sys.stderr)
            self._safe_500()

    def _safe_500(self) -> None:
        try:
            self._msg(400, "badreq")
        except Exception:  # noqa: BLE001
            pass

    # -- approval ---------------------------------------------------------
    def _get_action(self, action_id: str, token: str) -> None:
        a = self.web.store.token_matches(action_id, token)
        if a is None:
            return self._msg(403, "forbidden")
        t = self._t()
        if a.status == "pending":
            return self._send(200, _render_approval(t, a))
        self._send(200, _render_status(t, a))

    def _post_action(self, action_id: str, form: dict[str, str]) -> None:
        t = self._t()
        token = form.get("t", "")
        act = form.get("action", "")
        if act not in ("approve", "reject"):
            return self._msg(400, "badreq")
        store = self.web.store
        try:
            a = store.approve(action_id, token) if act == "approve" else store.reject(action_id, token)
        except InvalidActionToken:
            return self._msg(403, "forbidden")
        except ActionNotPending as e:
            return self._send(409, _render_message(t, t["conflict_title"], str(e)))
        except MailMcpError as e:
            return self._send(409, _render_message(t, t["conflict_title"], str(e)))
        self._send(200, _render_status(t, a))

    # -- add account ------------------------------------------------------
    def _get_add(self, q: dict[str, str]) -> None:
        token = q.get("t", "")
        if not self.web._session_valid(token):
            return self._msg(403, "forbidden")
        t = self._t()
        values: dict = {}
        info = None
        email = (q.get("email") or "").strip()
        if email:
            values["email"] = email[:254]
            try:
                info = dict(self.web.lookup(email) or {})
            except MailMcpError as e:
                info = {"error": str(e)}
            except Exception:  # noqa: BLE001
                info = {"error": t["err_lookup"]}
            if info and not info.get("error"):
                for k in ("imap_host", "imap_port", "imap_security",
                          "smtp_host", "smtp_port", "smtp_security"):
                    if info.get(k) not in (None, ""):
                        values[k] = str(info[k])
        self._send(200, _render_add(t, token, values, info=info))

    def _post_add_microsoft(self, form: dict[str, str]) -> None:
        t = self._t()
        token = form.get("t", "")
        if not self.web._session_valid(token) or self.web.add_oauth is None:
            return self._msg(403, "forbidden")
        email = form.get("email", "").strip()[:254]
        display_name = form.get("display_name", "").strip()[:300]
        values = {"email": email, "display_name": display_name}

        def redisplay(err: str) -> None:
            try:
                info = dict(self.web.lookup(email) or {})
            except Exception:  # noqa: BLE001
                info = None
            self._send(200, _render_add(t, token, values, error=err, info=info))

        if "@" not in email or any(c.isspace() for c in email):
            return redisplay(t["err_email"])
        with self.web._add_lock:
            if not self.web._session_valid(token):
                return self._msg(403, "forbidden")
            try:
                account_id = self.web.add_oauth(email, display_name)
            except MailMcpError as e:
                return redisplay(str(e))
            except Exception as e:  # noqa: BLE001
                print(f"mailmcp web: add_oauth crashed: {type(e).__name__}", file=sys.stderr)
                return redisplay(t["err_generic"])
            self.web._session_consume(token)
        self.web._added.put(account_id)
        self._send(200, _render_message(t, t["added_title"], t["added_text"].format(id=account_id)))

    def _post_add(self, form: dict[str, str]) -> None:
        t = self._t()
        token = form.get("t", "")
        if not self.web._session_valid(token):
            return self._msg(403, "forbidden")
        values = {k: form.get(k, "").strip()[:300] for k in _AddForm.FIELDS}
        password = form.get("password", "")

        def redisplay(err: str, status: int = 200) -> None:
            info = None
            try:
                info = dict(self.web.lookup(values["email"]) or {}) if "@" in values["email"] else None
            except Exception:  # noqa: BLE001 - redisplay must not fail on lookup
                info = None
            self._send(status, _render_add(t, token, values, error=err, info=info))

        if "@" not in values["email"] or any(c.isspace() for c in values["email"]):
            return redisplay(t["err_email"])
        if not password:
            return redisplay(t["err_password"])
        manual = None
        if values["imap_host"] or values["smtp_host"]:
            try:
                manual = {
                    "imap_host": values["imap_host"],
                    "imap_port": int(values["imap_port"] or 993),
                    "imap_security": values["imap_security"] or "ssl",
                    "smtp_host": values["smtp_host"],
                    "smtp_port": int(values["smtp_port"] or 465),
                    "smtp_security": values["smtp_security"] or "ssl",
                    "username": values["username"] or values["email"],
                }
            except ValueError:
                return redisplay(t["err_port"])
            if manual["imap_security"] not in ("ssl", "starttls") or \
                    manual["smtp_security"] not in ("ssl", "starttls"):
                return redisplay(t["err_security"])
        with self.web._add_lock:
            if not self.web._session_valid(token):
                return self._msg(403, "forbidden")
            try:
                account_id = self.web.add_account(values["email"], password,
                                                  values["display_name"], manual)
            except MailMcpError as e:
                return redisplay(str(e))
            except Exception as e:  # noqa: BLE001
                print(f"mailmcp web: add_account crashed: {type(e).__name__}", file=sys.stderr)
                return redisplay(t["err_generic"])
            self.web._session_consume(token)
        self.web._added.put(account_id)
        self._send(200, _render_message(t, t["added_title"], t["added_text"].format(id=account_id)))


class LocalWeb:
    def __init__(self, store: ActionStore, add_account: AddAccountHandler, lookup: LookupHandler,
                 host: str = "127.0.0.1", port: int = 0,
                 add_oauth: Callable[[str, str], str] | None = None) -> None:
        self.store = store
        self.add_account = add_account
        self.add_oauth = add_oauth
        self.lookup = lookup
        self._host = host
        self._req_port = port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._add_lock = threading.Lock()
        self._sess_lock = threading.Lock()
        self._sessions: dict[str, float] = {}
        self._added: "queue.Queue[str]" = queue.Queue()

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else 0

    def start(self) -> None:
        """Idempotent; ThreadingHTTPServer in a daemon thread. Port 0 = random free port."""
        with self._start_lock:
            if self._server is not None:
                return
            srv = _Server((self._host, self._req_port), _Handler)
            srv.web = self
            self._server = srv
            self._thread = threading.Thread(target=srv.serve_forever, name="mailmcp-web", daemon=True,
                                            kwargs={"poll_interval": 0.1})
            self._thread.start()

    def stop(self) -> None:
        with self._start_lock:
            srv, self._server = self._server, None
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def base_url(self) -> str:
        """'http://127.0.0.1:<port>' (starts the server if needed)."""
        self.start()
        return f"http://127.0.0.1:{self.port}"

    def approval_url(self, action_id: str) -> str:
        """base_url + '/a/<id>?t=<token>'."""
        a = self.store.get(action_id)
        if a is None:
            raise MailMcpError(f"Unknown action {action_id}")
        return f"{self.base_url}/a/{urllib.parse.quote(a.id)}?t={urllib.parse.quote(a.token)}"

    def new_add_account_url(self) -> str:
        """Create a single-use add-account session token (30 min) and return base_url + '/add?t=<token>'."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._sess_lock:
            for k in [k for k, exp in self._sessions.items() if exp < now]:
                del self._sessions[k]
            self._sessions[token] = now + ADD_SESSION_SECONDS
        return f"{self.base_url}/add?t={token}"

    def _session_valid(self, token: str) -> bool:
        if not token:
            return False
        now = time.time()
        with self._sess_lock:
            ok = False
            for k, exp in self._sessions.items():  # constant-time over all candidates
                if hmac.compare_digest(k.encode(), token.encode("utf-8", "replace")) and exp >= now:
                    ok = True
            return ok

    def _session_consume(self, token: str) -> None:
        with self._sess_lock:
            self._sessions.pop(token, None)

    def wait_for_add(self, timeout: float) -> str | None:
        """Block until an account is added via the page (returns its id) or timeout (None). Used by CLI."""
        try:
            return self._added.get(timeout=timeout)
        except queue.Empty:
            return None


def open_in_browser(url: str) -> bool:
    """webbrowser.open in a background thread; return False if no browser available (never raise)."""
    try:
        result: list[bool] = []

        def run() -> None:
            try:
                result.append(bool(webbrowser.open(url)))
            except Exception:  # noqa: BLE001
                result.append(False)

        th = threading.Thread(target=run, name="mailmcp-open-browser", daemon=True)
        th.start()
        th.join(timeout=3)
        return bool(result and result[0])
    except Exception:  # noqa: BLE001
        return False
