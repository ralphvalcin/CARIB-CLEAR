-- webhook / delivery / config infrastructure

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    events TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    secret TEXT NOT NULL,
    description TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 10,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);

CREATE INDEX IF NOT EXISTS idx_webhooks_participant ON webhooks(participant_id);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    delivery_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    status_code INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    attempt_number INTEGER DEFAULT 1,
    duration_ms REAL DEFAULT 0.0,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (webhook_id) REFERENCES webhooks(webhook_id)
);

CREATE INDEX IF NOT EXISTS idx_deliveries_webhook ON delivery_attempts(webhook_id);

CREATE TABLE IF NOT EXISTS webhook_delivery_queue (
    delivery_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    attempt_number INTEGER DEFAULT 1,
    error_message TEXT DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('queued','processing','done','failed')),
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_queue_webhook ON webhook_delivery_queue(webhook_id);
