# Security

mailmcp gives an AI agent access to real mailboxes, so this file states plainly what the
design protects and what it does not.

## What is protected

- **Passwords stay out of the chat.** An app password is typed into a page served on
  `127.0.0.1`, verified with an IMAP login, and stored in the OS keyring (Windows Credential
  Manager, macOS Keychain, Linux Secret Service). It is never written to config files,
  environment variables, logs or tool output. If no secure keyring backend exists, mailmcp
  refuses to add the account instead of falling back to plaintext.
- **Sending and trashing are enforced by the server.** The agent can only *request* an action.
  The server holds the real recipients, subject and body, shows them on a local approval page,
  and executes only after a human clicks Approve. Requests expire after 15 minutes and live in
  memory only, so they vanish when the server stops.
- **Loosening settings needs a click too.** Turning approval back on is immediate; turning it
  off creates an approval request like any other action.
- **No permanent delete.** "Trash" moves mail to the provider's Trash folder. mailmcp has no
  expunge or hard-delete path.
- **Mail content is wrapped as untrusted.** Every message returned to the agent is placed inside
  a fence carrying a random nonce and preceded by a warning not to follow instructions in it.
  Hidden HTML (`display:none`, zero font size, `hidden` attributes and similar) is removed first.
- **Reading is side-effect free.** Messages are fetched with `BODY.PEEK` on read-only folder
  selections, so they are not marked as read.
- **The local web page is hardened.** It binds to `127.0.0.1` on a random port; requests whose
  `Host` is not `127.0.0.1:<port>` or `localhost:<port>` are rejected (DNS rebinding); POSTs
  need a matching `Origin` (or none) and a secret token; tokens are 256-bit, single-use,
  compared in constant time, and expire (15 minutes for approvals, 30 for add-account sessions);
  a strict Content-Security-Policy is sent; the pages contain no JavaScript; all output is
  HTML-escaped.
- **The agent never sees approval links.** The secret approval URL is opened directly in the
  user's browser and is not included in tool output, so an agent with a shell (curl) cannot
  approve its own request. If no browser can be opened, approval cannot happen at all.

## What is NOT protected

- **Mail content goes to your AI provider.** Anything the agent reads is sent to the model
  vendor you use (Anthropic, OpenAI, Google, ...). Do not connect mailboxes you would not show
  to that provider.
- **Anyone who can act as your logged-in OS user can read the keyring.** Malware or another
  process running as you can ask the keyring for the stored passwords. mailmcp does not defend
  against a compromised user session.
- **An agent with an unrestricted shell is "your OS user".** The approval guarantee is complete
  for agents that only use mailmcp's tools, and for agents whose shell commands you approve one by
  one. If you let an agent run arbitrary commands without asking (for example a "bypass
  permissions" or "full auto" mode), it could read the keyring or talk to your mail provider
  directly, outside mailmcp. mailmcp makes the safe path the easy one (the agent never sees
  approval links or passwords) but cannot sandbox the agent itself.
- **Prompt injection can still steer the agent.** An email can persuade the agent to draft
  something harmful or to *request* a send or trash. The server will not execute it without a
  click, but the click is the last line of defence: **read the approval page**, which shows the
  actual recipients and body, not the agent's summary.
- **App passwords are full-mailbox credentials.** They grant read, send and delete at the
  provider, independent of mailmcp's approvals. When you uninstall or stop using mailmcp, run
  `mailmcp remove-account <id>` and also revoke the app password at the provider.
- **Approval can be disabled** (see below), after which an injected instruction can send mail
  with no human in the loop.

## Approval can be turned off

You can ask the agent to turn off `send_approval` or `trash_approval` through the `settings`
tool. Doing so is itself a pending action: a local page lists the change and nothing happens
until you click Approve. An agent (or an email steering one) therefore cannot silently remove
the safeguard. The approved change is signed with a key kept in the OS keyring; an "off" written
into `config.json` by hand (or by an agent with a file-editing tool) has no valid signature and
is ignored, so approvals stay on. Turning approval back on needs no click. Leave approvals on unless you have a
specific reason.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting: on the
repository, go to **Security -> Report a vulnerability** (a private security advisory).
Include the version, platform, and steps to reproduce. This is a single-maintainer project,
so please allow a few days for a reply.
