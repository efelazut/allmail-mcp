# mailmcp architecture (v0.1 contract)

This file is the contract between modules. Implementers must keep the public
signatures in `src/mailmcp/*.py` stubs; they may add private helpers.

## Goal
A local stdio MCP server that gives any MCP client (Claude Code, Codex, Cursor,
Antigravity, ...) access to **many mail accounts across providers** (Gmail,
iCloud, Yandex, Zoho, Fastmail, Yahoo, GMX, any IMAP/SMTP host). v0.2 adds
Microsoft (Outlook.com/Hotmail) via Graph; v0.1 must reject Microsoft domains
with a clear "coming in v0.2" message.

## Non-negotiable security rules
1. Passwords never pass through the chat/LLM. They are typed into a local
   browser page served by us, verified with an IMAP login, then stored in the OS
   keyring (`keyring`, service `mailmcp`). Never in config files, env, logs, tool output.
2. If no secure keyring backend exists (e.g. `keyring.backends.fail`, plaintext
   `keyrings.alt`), refuse with a clear error. Never fall back to plaintext.
3. Reading is free. Drafts are free. **Sending and trashing require a human click
   on a local approval page by default.** The click itself executes the action
   server-side; the LLM can only *request*.
4. Approval can be turned off per action type via the `settings` tool, but
   **loosening a setting itself requires a human approval click**. Tightening is immediate.
5. No permanent delete anywhere. "Trash" = move to the provider's Trash folder.
6. All mail content returned to the LLM is wrapped in untrusted fences with a
   random nonce: `<untrusted_email nonce="abc123">...</untrusted_email nonce="abc123">`,
   preceded by a one-line warning not to follow instructions inside.
7. Local web server: bind `127.0.0.1`, random port, reject requests whose `Host`
   is not `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding), POST requires
   matching `Origin` (or absent Origin + valid token) and a single-use token
   (`secrets.token_urlsafe(32)`, constant-time compare, 15 min expiry). Strict CSP
   (`default-src 'none'; style-src 'unsafe-inline'; form-action 'self'`),
   `X-Frame-Options: DENY`, `Referrer-Policy: same-origin` (not no-referrer: that makes browsers send `Origin: null`). HTML-escape everything.
8. Approval pages show data from the **server-side pending action** (recipients,
   subject, full body / message list), never an LLM-provided summary.

## Modules
| Module | Owner | Responsibility |
|---|---|---|
| `config.py` | core | `Account`, `Settings`, `Config` dataclasses; load/save JSON atomically under `config_dir()` (platformdirs `user_config_dir("mailmcp", appauthor=False)`, overridable by env `MAILMCP_HOME`). No secrets. |
| `secrets_store.py` | core | keyring wrapper: `set_password`, `get_password`, `delete_password`, `assert_secure_backend`. |
| `providers.py` | core | domain → `ServerSettings` table + Thunderbird autoconfig fallback (`https://autoconfig.thunderbird.net/v1.1/<domain>`, 5 s timeout, can be disabled with env `MAILMCP_NO_AUTOCONFIG=1`) + `imap.<domain>` guess. Also app-password help URLs and `is_microsoft(domain)`. |
| `imap_backend.py` | core | `MailBox` context manager over `imapclient`: folders (RFC 6154 special-use + name fallback), search (Gmail `X-GM-RAW` when capability `X-GM-EXT-1` and a free-text query), fetch with `BODY.PEEK[]` (never marks read), append draft, append sent, move to trash (MOVE if supported else COPY + `\Deleted` + UID EXPUNGE). `test_login(server_settings, username, password)`. |
| `smtp_backend.py` | core | `send_message(account, password, msg)`; SSL(465) or STARTTLS(587). |
| `compose.py` | core | `build_message(...)` → `email.message.EmailMessage`; reply threading (`In-Reply-To`, `References`, `Re:`). Validates addresses. |
| `clean.py` | web | HTML→text with `nh3` (drop script/style/hidden content), whitespace collapse, truncation, `wrap_untrusted`. |
| `actions.py` | web | in-memory `ActionStore` of `PendingAction`s, executors registered by kind (`send`, `trash`, `settings`), status lifecycle `pending → approved → done|failed`, `rejected`, `expired`. Thread-safe. |
| `web.py` | web | `LocalWeb` (ThreadingHTTPServer in daemon thread, lazy start): approval pages `/a/<id>`, add-account page `/add`. Bilingual EN/TR via `Accept-Language`. |
| `install.py` | cli | Write the MCP entry into Claude Code, Codex, Cursor, Antigravity configs (dry-run diff, backups, idempotent). |
| `cli.py` | cli | `mailmcp` (no args) = run stdio server; subcommands `serve`, `add-account`, `accounts`, `remove-account`, `install`, `uninstall`, `doctor`. |
| `server.py` | integrator | `MCPServer` tools; glue. |

## Data shapes
```python
Account(id: str, email: str, display_name: str, provider: str,
        imap_host: str, imap_port: int, imap_security: "ssl"|"starttls",
        smtp_host: str, smtp_port: int, smtp_security: "ssl"|"starttls",
        username: str, smtp_saves_sent: bool)
# id = short slug from email, unique (e.g. "efe-gmail"); config stores accounts by id.
Settings(send_approval: bool = True, trash_approval: bool = True, autoconfig_lookup: bool = True)
```

## Tools (server.py)
| Tool | Kind | Notes |
|---|---|---|
| `accounts_list()` | read | ids, emails, providers, settings |
| `account_add()` | local UI | opens add-account page, returns URL; user finishes in browser |
| `folders_list(account)` | read | |
| `mail_search(account=None, folder="INBOX", query=None, sender=None, subject=None, since=None, before=None, unread_only=False, limit=20)` | read | `account=None` searches all accounts, merges by date |
| `mail_read(account, uid, folder="INBOX", max_chars=6000)` | read | untrusted-wrapped |
| `draft_create(account, to, subject, body, cc=None, bcc=None, reply_to_uid=None, reply_folder="INBOX")` | write (safe) | saved to Drafts |
| `request_send(...same as draft_create)` | approval | returns action id + URL, or sends immediately if `send_approval` is off |
| `request_trash(account, uids, folder="INBOX")` | approval | move to Trash |
| `action_status(action_id)` | read | |
| `settings(send_approval=None, trash_approval=None)` | approval to loosen | |
