-- Eenmalige, actor-/procesgebonden bevestiging van publieke configuratie.
CREATE TABLE configuration_imports (
    token_hash TEXT PRIMARY KEY,
    actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    instance_id TEXT NOT NULL,
    document_json TEXT NOT NULL,
    baseline_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);
