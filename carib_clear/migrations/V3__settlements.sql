-- settlement ledger / events / audit

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    business_key TEXT NOT NULL,
    rail TEXT NOT NULL,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    currency_from TEXT NOT NULL,
    currency_to TEXT NOT NULL,
    amount_from REAL NOT NULL,
    amount_to REAL NOT NULL,
    rate REAL NOT NULL,
    fees_usd REAL NOT NULL DEFAULT 0,
    tx_hash TEXT,
    error_message TEXT DEFAULT '',
    raw_response TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_settlements_scope_business ON settlements(scope, business_key);
CREATE INDEX IF NOT EXISTS idx_settlements_order ON settlements(order_id);
CREATE INDEX IF NOT EXISTS idx_settlements_status ON settlements(status);

CREATE TABLE IF NOT EXISTS settlement_events (
    event_id TEXT PRIMARY KEY,
    settlement_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    source TEXT,
    confirmed_at TEXT NOT NULL,
    FOREIGN KEY (settlement_id) REFERENCES settlements(settlement_id)
);

CREATE INDEX IF NOT EXISTS idx_settlement_events_settlement ON settlement_events(settlement_id);
