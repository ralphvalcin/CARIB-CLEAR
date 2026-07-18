-- participants / identity

CREATE TABLE IF NOT EXISTS participants (
    participant_id TEXT PRIMARY KEY,
    type TEXT NOT NULL DEFAULT 'msme',
    name TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS participant_api_keys (
    key_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    prefix TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);

CREATE INDEX IF NOT EXISTS idx_participant_api_keys_participant ON participant_api_keys(participant_id);
CREATE INDEX IF NOT EXISTS idx_participant_api_keys_prefix ON participant_api_keys(prefix);
