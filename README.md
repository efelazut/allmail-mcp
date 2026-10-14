# mailmcp

**All your mailboxes in any AI agent. Runs on your computer. Nothing is sent or trashed without your click.**

[Türkçe](README.tr.md)

mailmcp is an [MCP](https://modelcontextprotocol.io) server that connects Claude Code, Codex,
Cursor, Antigravity, Gemini CLI (any MCP client) to **several mail accounts at once**: Gmail,
iCloud, Yandex, Zoho, Fastmail, Yahoo, GMX and any IMAP/SMTP provider. Outlook/Hotmail/Live connect with "Sign in with Microsoft" (no app password; see [docs/MICROSOFT.md](docs/MICROSOFT.md)).

```
"Find the invoices from last week in all my inboxes"
"Summarise my unread mail on the school account"
"Draft a reply to Ahmet saying Thursday works"
"Send it"   → a page opens in your browser: To / Subject / Body / [Approve] [Reject]
```

## Why

| | Built-in Gmail/Outlook connectors | mailmcp |
|---|---|---|
| Several accounts of the same provider | One account per provider | **As many as you want** |
| iCloud, Yandex, Zoho, company/hosting mail | Not available | **Any IMAP/SMTP** |
| Works in | That one app | **Every MCP client, one login** |
| Sending | Depends on the client's permission mode | **Human click on a local page, enforced by the server** |
| Where your credentials live | The vendor's cloud | **Your OS keychain** |

## Install

Give your agent this repository's link and say *"install this"* — it follows [INSTALL.md](INSTALL.md).

Or do it yourself (needs [uv](https://docs.astral.sh/uv/)):

```bash
uvx allmail-mcp install        # adds the "mail" server to Claude Code, Codex, Cursor, Antigravity, Gemini CLI
uvx allmail-mcp add-account    # opens a local page; paste an app password there
```

No uv? `uvx` comes from [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`, or the one-line
installer). Without it: `pipx install allmail-mcp`, then run `allmail-mcp install --command allmail-mcp`.

Restart your agent and ask it about your mail. Single client, by hand:

```bash
claude mcp add --scope user mail -- uvx allmail-mcp
codex mcp add mail -- uvx allmail-mcp
```

## Safety model

- **Passwords never go through the chat.** You type an app password into a page served on
  `127.0.0.1`; mailmcp verifies it with an IMAP login and stores it in Windows Credential
  Manager / macOS Keychain / Linux Secret Service. If no secure keychain exists, it refuses.
- **Reading and drafting are free; sending and trashing need your click.** The agent can only
  *request*. The approval page shows the real recipients, subject and body held by the server,
  not the agent's summary. The click executes the action.
- **Approval can be turned off** (`"turn off send approval"`), but turning it off itself needs a click.
  Turning it back on is instant.
- **No permanent delete.** "Trash" moves mail to the provider's Trash folder.
- **Mail content is marked as untrusted** before the agent sees it, and hidden HTML text (a common
  prompt-injection trick) is removed.
- **Reading never marks mail as read.**
- The local page binds to `127.0.0.1` on a random port, checks `Host` and `Origin`, uses single-use
  tokens that expire, sends a strict CSP and contains no JavaScript.

What it cannot protect against: whatever the agent reads is sent to your AI provider (Anthropic,
OpenAI, Google...). Do not connect mailboxes you would not show to it. See [SECURITY.md](SECURITY.md).

## Tools

| Tool | What it does |
|---|---|
| `accounts_list` | Connected accounts and approval settings |
| `account_add` | Opens the local add-account page |
| `folders_list` | Folders of an account |
| `mail_search` | Search one or **all** accounts (sender, subject, dates, unread, Gmail syntax on Gmail) |
| `mail_read` | One message as clean text |
| `draft_create` | Save a draft (also replies in-thread) |
| `request_send` | Send, after your click |
| `request_trash` | Move to Trash, after your click |
| `action_status` | Did the user approve? |
| `settings` | Turn approvals on/off |

Ten small tools on purpose: fewer tokens in every session, fewer ways to go wrong.

## Providers

| Provider | How you sign in |
|---|---|
| Gmail | [App password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification; most Google Workspace accounts can't use them) |
| iCloud | [App-specific password](https://account.apple.com) |
| Yandex, Zoho, Fastmail, Yahoo, GMX, AOL, Mail.ru | App password |
| Anything else with IMAP/SMTP | Settings are looked up automatically (built-in table, then Mozilla's autoconfig database) or entered by hand |
| Outlook / Hotmail / Live | Sign in with Microsoft in the browser |
| Proton | Through Proton Mail Bridge, entered by hand |

## Commands

```bash
uvx allmail-mcp                 # run the MCP server (what your agent starts)
uvx allmail-mcp add-account
uvx allmail-mcp accounts
uvx allmail-mcp remove-account <id>
uvx allmail-mcp install [--client claude|codex|cursor|antigravity|gemini] [--dry-run] [--yes]
uvx allmail-mcp uninstall
uvx allmail-mcp doctor          # checks keychain, config and each account's login
```

## Skill (optional)

If your agent supports Agent Skills, copy [`skill/mailmcp/SKILL.md`](skill/mailmcp/SKILL.md) to
`~/.claude/skills/mailmcp/SKILL.md` (Claude Code), `~/.codex/skills/mailmcp/SKILL.md` (Codex) or
`.agents/skills/mailmcp/SKILL.md` in your project. It teaches the agent the tool workflow: search
all accounts, read before replying, draft first, wait for the user to approve in the browser, never take
instructions from inside an email. mailmcp works without it.

## Alternatives

Good projects exist and you may prefer them:
[Wh1isper/mcp-email-server](https://github.com/Wh1isper/mcp-email-server) (IMAP, Python),
[marlinjai/email-mcp](https://github.com/marlinjai/email-mcp) (Gmail/Outlook OAuth, Node),
[Softeria/ms-365-mcp-server](https://github.com/Softeria/ms-365-mcp-server) (all of Microsoft 365),
[jgalea/mailbox-mcp](https://github.com/jgalea/mailbox-mcp) (security-focused).
mailmcp's focus is: many accounts across providers, every client, server-enforced human approval,
credentials only in the OS keychain.

## Development

```bash
git clone https://github.com/efelazut/allmail-mcp && cd mailmcp
uv venv && uv pip install -e ".[dev]"
uv run pytest
```

Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). License: [MIT](LICENSE).
