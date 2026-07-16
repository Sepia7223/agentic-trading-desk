"""Typed journal failures without secret-bearing diagnostics."""


class JournalError(Exception):
    """Base class for durable-journal failures."""


class JournalConfigurationError(JournalError):
    """The journal configuration is unsafe or incomplete."""


class JournalSchemaError(JournalError):
    """The database schema cannot be safely used."""


class UnsupportedSchemaError(JournalSchemaError):
    """The database was created by an unsupported newer schema."""


class JournalDuplicateError(JournalError):
    """An immutable journal or source identity already exists."""


class JournalParentMissingError(JournalError):
    """A required source parent is absent."""


class JournalIntegrityError(JournalError):
    """Append-only integrity validation failed."""


class JournalReadOnlyRecoveryError(JournalIntegrityError):
    """The repository is available for recovery reads only."""


class JournalExportError(JournalError):
    """A bounded, sanitized export could not be produced."""


class JournalBackupError(JournalError):
    """A consistent journal backup could not be produced or verified."""
