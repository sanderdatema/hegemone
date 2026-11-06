-- Beheersbare credential-, memory- en kostenbegrenzing (BETON-499/500/505).
ALTER TABLE users ADD COLUMN api_key_expires_at TEXT;
ALTER TABLE users ADD COLUMN api_key_scopes TEXT;
ALTER TABLE users ADD COLUMN api_key_projects TEXT;

CREATE TABLE browser_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_fingerprint TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX browser_sessions_user ON browser_sessions(user_id);

ALTER TABLE wiki_pages ADD COLUMN protected INTEGER NOT NULL DEFAULT 0;
ALTER TABLE wiki_pages ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE wiki_pages ADD COLUMN source_author_id INTEGER REFERENCES users(id);
-- Bestaande globale regels worden beschermd, agentprojectkennis blijft bewerkbaar.
UPDATE wiki_pages SET protected = 1 WHERE project_id IS NULL;
CREATE TABLE wiki_proposals (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id),
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    body_md TEXT NOT NULL,
    author_id INTEGER NOT NULL REFERENCES users(id),
    base_updated_at TEXT,
    base_digest TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    reviewed_at TEXT,
    reviewed_by INTEGER REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected'))
);
CREATE INDEX wiki_proposals_pending ON wiki_proposals(project_id,status);

CREATE TABLE llm_daily_usage (
    day TEXT NOT NULL,
    category TEXT NOT NULL,
    spent INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(day,category)
);

CREATE TABLE api_write_usage (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    total_bytes INTEGER NOT NULL DEFAULT 0,
    day TEXT NOT NULL,
    day_bytes INTEGER NOT NULL DEFAULT 0
);
