-- Betonning schema 001 — alle kerntabellen.
-- Zie het plan (Datamodel-sectie) voor de rationale per tabel.
-- Migratierunner zet PRAGMA user_version = 1 na succes.

CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    handle        TEXT NOT NULL UNIQUE,          -- voor @mentions
    display_name  TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('human', 'agent')),
    api_key_hash  TEXT NOT NULL UNIQUE,          -- sha256-hex van de API-key
    webhook_url   TEXT,                          -- nullable; alleen Hermes-agents
    webhook_secret TEXT,
    subscribe_all INTEGER NOT NULL DEFAULT 0,    -- triage-rol: ontvangt alle events
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE projects (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,            -- ticket-prefix, bv. "SOS"
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    next_seq    INTEGER NOT NULL DEFAULT 1,      -- volgend sequence-nummer
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE states (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    grp         TEXT NOT NULL CHECK (grp IN ('backlog', 'unstarted', 'started', 'completed', 'cancelled')),
    color       TEXT NOT NULL DEFAULT '#95a5a6',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_default  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, name)
);

CREATE TABLE milestones (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed')),
    due_date    TEXT,
    UNIQUE (project_id, name)
);

CREATE TABLE labels (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL DEFAULT '#95a5a6',
    UNIQUE (project_id, name)
);

CREATE TABLE items (
    id             INTEGER PRIMARY KEY,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,             -- uniek per project → "SOS-42"
    title          TEXT NOT NULL,
    description_md TEXT NOT NULL DEFAULT '',
    state_id       INTEGER REFERENCES states(id),
    priority       TEXT NOT NULL DEFAULT 'none'
                        CHECK (priority IN ('urgent', 'high', 'medium', 'low', 'none')),
    assignee_id    INTEGER REFERENCES users(id),
    created_by     INTEGER REFERENCES users(id),
    parent_id      INTEGER REFERENCES items(id),
    milestone_id   INTEGER REFERENCES milestones(id),
    plane_id       TEXT UNIQUE,                  -- voor idempotente migratie
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    completed_at   TEXT,
    UNIQUE (project_id, seq)
);

CREATE INDEX idx_items_project_state ON items(project_id, state_id);
CREATE INDEX idx_items_assignee ON items(assignee_id);
CREATE INDEX idx_items_parent ON items(parent_id);

CREATE TABLE item_labels (
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, label_id)
);

CREATE TABLE comments (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    author_id  INTEGER REFERENCES users(id),
    body_md    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_comments_item ON comments(item_id);

-- Relaties: richting bepaalt de betekenis.
--   type='blocks'       → item_id blokkeert related_item_id (related is blocked_by item)
--   type='duplicate_of' → item_id is duplicaat van related_item_id
--   type='relates_to'   → symmetrisch
CREATE TABLE relations (
    id              INTEGER PRIMARY KEY,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    related_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN ('duplicate_of', 'blocks', 'relates_to')),
    UNIQUE (item_id, related_item_id, type)
);

CREATE INDEX idx_relations_item ON relations(item_id);
CREATE INDEX idx_relations_related ON relations(related_item_id);

-- Append-only activity log; voedt activity-feed én webhooks.
CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    type        TEXT NOT NULL,
    item_id     INTEGER REFERENCES items(id) ON DELETE CASCADE,
    actor_id    INTEGER REFERENCES users(id),
    payload     TEXT NOT NULL DEFAULT '{}',      -- JSON
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_events_item ON events(item_id);

CREATE TABLE webhook_deliveries (
    id            INTEGER PRIMARY KEY,
    event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'delivered', 'failed')),
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    next_retry_at TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_deliveries_status ON webhook_deliveries(status);

-- FTS5 over items (title + description) voor zoeken. content-rowid = items.id.
CREATE VIRTUAL TABLE items_fts USING fts5(
    title,
    description_md,
    content='items',
    content_rowid='id'
);

CREATE TRIGGER items_fts_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, description_md)
    VALUES (new.id, new.title, new.description_md);
END;

CREATE TRIGGER items_fts_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, description_md)
    VALUES ('delete', old.id, old.title, old.description_md);
END;

CREATE TRIGGER items_fts_au AFTER UPDATE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, description_md)
    VALUES ('delete', old.id, old.title, old.description_md);
    INSERT INTO items_fts(rowid, title, description_md)
    VALUES (new.id, new.title, new.description_md);
END;
