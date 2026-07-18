-- loans / compliance / serialized tables

CREATE TABLE IF NOT EXISTS loan_applications (
    application_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    business_name TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    jurisdiction TEXT NOT NULL,
    approved INTEGER DEFAULT 0,
    lender TEXT,
    interest_rate_pct REAL,
    sector TEXT,
    purpose TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);

CREATE INDEX IF NOT EXISTS idx_loans_participant ON loan_applications(participant_id);

CREATE TABLE IF NOT EXISTS compliance_checks (
    check_id TEXT PRIMARY KEY,
    participant_id TEXT,
    check_type TEXT NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    details TEXT NOT NULL DEFAULT '{}',
    requires_review INTEGER NOT NULL DEFAULT 0,
    reviewer_notes TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aml_pep_hits (
    hit_id TEXT PRIMARY KEY,
    participant_id TEXT,
    check_id TEXT NOT NULL,
    issue TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queues (
    queue_id TEXT PRIMARY KEY,
    check_id TEXT NOT NULL,
    participant_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
