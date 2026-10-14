# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] - Unreleased

### Added
- Outlook.com / Hotmail / Live accounts: "Sign in with Microsoft" on the add-account page (MSAL
  browser sign-in, IMAP + SMTP over XOAUTH2, no app password). Tokens are stored in an encrypted
  cache whose key is in the OS keyring. See docs/MICROSOFT.md.

### Fixed
- Local pages no longer lose their error response on Windows when a POST is rejected before its
  body is read (the server drains small bodies first).

## [0.1.2] - 2026-10-14

### Changed
- Add-account page is now a guided flow: first only the address, then numbered steps
  (open the provider's app password page, paste the code, Connect). Server settings moved
  under "More options".

### Fixed
- A browser-autofilled username equal to the address no longer turns Gmail into a "custom"
  account (which lost provider defaults such as Gmail saving Sent copies itself).
- After a failed attempt the page keeps the provider steps and link.

## [0.1.1] - 2026-10-14

### Changed
- PyPI distribution renamed to `allmail-mcp`; repo moved to `efelazut/allmail-mcp`.
  `install` pins `uvx allmail-mcp@<version>` and still recognises older `mailmcp` entries.
- CLI shows its name as `allmail-mcp`. README documents a pipx fallback for users without uv.

## [0.1.0] - 2026-10-14

### Added
- MCP stdio server with ten tools: `accounts_list`, `account_add`, `folders_list`,
  `mail_search`, `mail_read`, `draft_create`, `request_send`, `request_trash`,
  `action_status`, `settings`.
- Multiple accounts across providers: Gmail, iCloud, Yandex, Zoho, Fastmail, Yahoo, GMX, AOL,
  Mail.ru and any IMAP/SMTP host (built-in table, then Mozilla autoconfig, then manual entry).
- Search one account or all accounts at once; Gmail search syntax on Gmail.
- Local add-account page on `127.0.0.1`; passwords verified over IMAP and stored only in the
  OS keyring. Refuses to run without a secure keyring backend.
- Server-enforced human approval page for sending and trashing, showing the real message.
- Approval settings that can be tightened instantly but need a click to loosen.
- Untrusted-content fencing with a random nonce and removal of hidden HTML.
- Non-destructive reads (`BODY.PEEK`); trash only, never permanent delete.
- Hardened local web server: random port, Host/Origin checks, single-use expiring tokens,
  strict CSP, no JavaScript. English and Turkish pages.
- CLI: `install`, `uninstall` (Claude Code, Codex, Cursor, Antigravity, Gemini CLI, with
  backups and `--dry-run`), `add-account`, `accounts`, `remove-account`, `doctor`.
- Optional Agent Skill in `skill/mailmcp/SKILL.md`.
- English and Turkish READMEs, SECURITY.md, INSTALL.md for agents.

### Not yet
- Outlook / Hotmail / Live (planned for v0.2).
