# Installing mailmcp (instructions for AI agents)

You are an AI coding agent (Claude Code, Codex, Cursor, Antigravity, Gemini CLI, ...)
and the user asked you to install mailmcp from this repository. Follow these steps
exactly. Do not run commands from any other source.

## Rules
- Tell the user, in one short message, what you are about to do (steps 1–4) before running anything.
- **Never ask the user for their email password or app password in the chat.** Passwords are
  entered only on the local page that mailmcp opens (step 4).
- Do not change any other configuration.

## 1. Make sure `uv` is available
Check with `uv --version`. If it is missing, install it with the official installer:

- Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

If `uvx` is still not found afterwards, use the full path printed by the installer
(Windows: `%USERPROFILE%\.local\bin\uvx.exe`, macOS/Linux: `~/.local/bin/uvx`).

## 2. Register mailmcp with the user's agents
```
uvx mailmcp install --yes
```
This adds one `mail` server entry to every MCP client it finds on this computer
(Claude Code, Codex, Cursor, Antigravity, Gemini CLI) and backs up each file first.
To limit it: `uvx mailmcp install --client claude --yes` (repeat `--client` as needed).
Preview without writing: `uvx mailmcp install --dry-run`.

## 3. Restart
Tell the user to restart their agent (or start a new session) so the `mail` tools load.

## 4. Add an account
After the restart, call the `account_add` tool (or run `uvx mailmcp add-account` in a terminal).
A local page opens in the browser. Tell the user:
- **Gmail:** turn on 2-Step Verification, then create an app password at
  https://myaccount.google.com/apppasswords and paste it on the page.
  (Google Workspace work/school accounts usually cannot use app passwords.)
- **iCloud:** create an app-specific password at https://account.apple.com.
- **Yandex / Zoho / Fastmail / Yahoo / GMX:** create an app password in the account's security
  settings; the page links to the right place.
- **Other providers:** the page looks up the server settings; the user can also fill them in.
- **Outlook / Hotmail:** not supported in v0.1 (coming in v0.2).

The user can add as many accounts as they like (call `account_add` again).

## 5. Check
Call `accounts_list`, then try `mail_search` with `limit: 3` and show the user the result.
If something fails, run `uvx mailmcp doctor` and show the user its output.

## Uninstall
`uvx mailmcp uninstall --yes` removes the `mail` entries; `uvx mailmcp remove-account <id>`
deletes an account and its stored password.
