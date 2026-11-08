-- Explicit, human-configured execution authority is separate from webhook delivery.
-- Execution metadata is bookkeeping; archived ticket content remains immutable.
CREATE TABLE execution_bindings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    profile TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    generation INTEGER NOT NULL DEFAULT 1,
    token_hash TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE execution_requests (
    id TEXT PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    profile TEXT NOT NULL,
    binding_generation INTEGER NOT NULL,
    intent_event_id INTEGER NOT NULL,
    revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','claimed','running','stopping','blocked','completed','cancelled')),
    block_kind TEXT CHECK (block_kind IN ('capability','transport','human','task','recovery','policy')),
    reason TEXT,
    missing_requirements TEXT NOT NULL DEFAULT '[]',
    responsible TEXT,
    resume_condition TEXT,
    block_digest TEXT,
    question_id INTEGER REFERENCES comments(id),
    run_id INTEGER REFERENCES execution_runs(id),
    fence INTEGER NOT NULL DEFAULT 0,
    transport_attempts INTEGER NOT NULL DEFAULT 0,
    retry_at REAL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE UNIQUE INDEX execution_one_active_item ON execution_requests(item_id)
    WHERE status NOT IN ('completed', 'cancelled');
CREATE INDEX execution_owner_status ON execution_requests(user_id,status);
CREATE INDEX execution_item_history ON execution_requests(item_id);

CREATE TABLE execution_runs (
    id INTEGER PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES execution_requests(id) ON DELETE CASCADE,
    fence INTEGER NOT NULL,
    owner TEXT NOT NULL,
    nonce_hash TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('claimed','running','blocked','completed','stopped','expired','recovery')),
    external_task_id TEXT,
    external_run_id TEXT,
    claimed_at REAL NOT NULL,
    started_at REAL,
    lease_until REAL NOT NULL,
    ended_at REAL,
    evidence TEXT NOT NULL DEFAULT '[]',
    UNIQUE (request_id, fence)
);

-- A live/ambiguous owner must be stopped before destructive cleanup can discard its fence.
CREATE TRIGGER execution_protect_live_owner_delete
BEFORE DELETE ON items
WHEN EXISTS (SELECT 1 FROM execution_requests r WHERE r.item_id=OLD.id
    AND (r.status IN ('claimed','running','stopping') OR (r.status='blocked' AND r.block_kind='recovery')))
BEGIN
    SELECT RAISE(ABORT, 'execution_owner_active');
END;
