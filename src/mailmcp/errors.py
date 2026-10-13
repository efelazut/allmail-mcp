"""Exceptions shared across modules. Messages must be safe to show to the LLM (no secrets)."""


class MailMcpError(Exception):
    """Base error; str(e) is shown to the user/LLM."""


class ConfigError(MailMcpError):
    pass


class SecretStoreError(MailMcpError):
    """No secure keyring backend, or keyring read/write failed."""


class AccountNotFound(MailMcpError):
    pass


class ProviderNotSupported(MailMcpError):
    """e.g. Microsoft personal accounts in v0.1."""


class MailServerError(MailMcpError):
    """IMAP/SMTP failure (login, network, protocol). Never include the password."""


class ComposeError(MailMcpError):
    """Invalid recipients or message fields."""


class InvalidActionToken(MailMcpError):
    """Unknown action id, wrong token, or token no longer valid."""


class ActionNotPending(MailMcpError):
    """Action already approved/done/rejected/expired."""


class UsageError(MailMcpError):
    """Bad command line usage (unknown client, bad --command)."""
