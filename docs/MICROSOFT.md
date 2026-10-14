# Microsoft (Outlook.com / Hotmail / Live) sign-in

Microsoft turned off password login for IMAP on personal accounts, so allmail-mcp connects
Outlook.com, Hotmail and Live addresses with OAuth 2.0: the add-account page shows
**Sign in with Microsoft**, Microsoft's own page opens in your default browser, you pick or sign
in to the account, and the mailbox is connected. allmail-mcp never sees your Microsoft password.

How it works:

- MSAL interactive flow (`acquire_token_interactive`) with a `http://localhost` redirect and the
  `consumers` authority.
- Scopes: `https://outlook.office.com/IMAP.AccessAsUser.All`, `https://outlook.office.com/SMTP.Send`
  (plus `offline_access`, added by MSAL). Mail is read over IMAP and sent over SMTP with XOAUTH2,
  through the same code paths as every other provider, including send/trash approval.
- Tokens are kept in an MSAL cache file (`ms_tokens.bin` in the config folder), encrypted with a
  key stored in the OS keyring. `remove-account` deletes the account's tokens.

## Using your own app registration

Release builds (0.2.0+) ship the allmail-mcp client id, so users just click "Sign in with Microsoft". To use your own (or for a development build):

1. Sign in at <https://entra.microsoft.com> → **App registrations** → **New registration**.
2. Name: anything (e.g. `allmail-mcp`). Supported account types: **Personal Microsoft accounts
   only** (or "any organizational directory and personal Microsoft accounts").
3. Redirect URI: platform **Public client/native (mobile & desktop)**, value `http://localhost`.
4. Register, then copy the **Application (client) ID**. No client secret is needed (public client).
5. **API permissions** → Add a permission → *APIs my organization uses* is not needed: the IMAP and
   SMTP scopes are requested at sign-in and consented by the user.
6. Run allmail-mcp with `MAILMCP_MS_CLIENT_ID=<that id>` in its environment.

The client id is not a secret; it identifies the app on Microsoft's consent screen.
