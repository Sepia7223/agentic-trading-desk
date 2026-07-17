"""Versioned SQLite schema for append-only journal evidence."""

SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS journal_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_records (
    sequence_number INTEGER PRIMARY KEY,
    journal_record_id TEXT NOT NULL UNIQUE,
    record_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_parent_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    instrument TEXT,
    epic TEXT,
    strategy_variant TEXT,
    environment TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    record_version INTEGER NOT NULL,
    source_fingerprint TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    previous_record_fingerprint TEXT,
    journal_record_fingerprint TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    deferred_linkage INTEGER NOT NULL DEFAULT 0 CHECK (deferred_linkage IN (0, 1)),
    atomic_group_id TEXT,
    atomic_group_index INTEGER,
    atomic_group_size INTEGER,
    UNIQUE(record_type, source_record_id)
);

CREATE TABLE IF NOT EXISTS journal_parent_links (
    child_journal_record_id TEXT NOT NULL,
    parent_source_record_id TEXT NOT NULL,
    parent_journal_record_id TEXT,
    deferred INTEGER NOT NULL DEFAULT 0 CHECK (deferred IN (0, 1)),
    PRIMARY KEY(child_journal_record_id, parent_source_record_id),
    FOREIGN KEY(child_journal_record_id) REFERENCES journal_records(journal_record_id),
    FOREIGN KEY(parent_journal_record_id) REFERENCES journal_records(journal_record_id)
);

CREATE TABLE IF NOT EXISTS journal_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    checksum TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_journal_records_effective_at
    ON journal_records(effective_at, sequence_number);
CREATE INDEX IF NOT EXISTS idx_journal_records_trading_day
    ON journal_records(trading_day, sequence_number);
CREATE INDEX IF NOT EXISTS idx_journal_records_type
    ON journal_records(record_type, sequence_number);
CREATE INDEX IF NOT EXISTS idx_journal_records_source
    ON journal_records(source_record_id);
CREATE INDEX IF NOT EXISTS idx_journal_records_instrument
    ON journal_records(instrument, sequence_number);
CREATE INDEX IF NOT EXISTS idx_journal_records_epic
    ON journal_records(epic, sequence_number);
CREATE INDEX IF NOT EXISTS idx_journal_records_atomic_group
    ON journal_records(atomic_group_id, atomic_group_index);
CREATE INDEX IF NOT EXISTS idx_journal_parent_source
    ON journal_parent_links(parent_source_record_id);
"""

SCHEMA_V2 = """
INSERT OR IGNORE INTO journal_metadata(key, value)
VALUES ('record_count', (SELECT CAST(COUNT(*) AS TEXT) FROM journal_records));

INSERT OR IGNORE INTO journal_metadata(key, value)
VALUES (
    'chain_head',
    COALESCE(
        (SELECT journal_record_fingerprint FROM journal_records
         ORDER BY sequence_number DESC LIMIT 1),
        ''
    )
);

CREATE TRIGGER IF NOT EXISTS journal_records_no_update
BEFORE UPDATE ON journal_records
BEGIN
    SELECT RAISE(ABORT, 'journal records are append-only');
END;

CREATE TRIGGER IF NOT EXISTS journal_records_no_delete
BEFORE DELETE ON journal_records
BEGIN
    SELECT RAISE(ABORT, 'journal records are append-only');
END;
"""
