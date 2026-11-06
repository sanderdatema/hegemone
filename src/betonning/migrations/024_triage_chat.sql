-- BETON-120: chat met triage. Gesprekken zijn geschaald als de wiki: precies
-- één globale thread (project_id IS NULL) + één thread per project. Binnen een
-- scope is er telkens één actieve (niet-gearchiveerde) sessie; archiveren
-- ("Nieuw gesprek") sluit 'm af zodat de volgende beurt een verse sessie
-- start met lege context (begrenst de LLM-context, naast het history-window
-- in de chat-motor zelf).
--
-- Pure CREATE TABLE (geen table-recreate) → FK-veilig op een gevulde DB.
-- Migratierunner zet PRAGMA user_version = 24 na succes.

CREATE TABLE triage_chat_sessions (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    archived_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_triage_chat_sessions_scope
    ON triage_chat_sessions(project_id, archived_at);

CREATE TABLE triage_chat_messages (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES triage_chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    author_id  INTEGER REFERENCES users(id),       -- de mens bij role='user'
    body_md    TEXT NOT NULL,
    -- Optioneel gekoppeld voorstel (JSON) dat wacht op bevestiging.
    proposal   TEXT,
    status     TEXT NOT NULL DEFAULT 'final'
                   CHECK (status IN ('final', 'pending', 'confirmed', 'cancelled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_triage_chat_messages_session
    ON triage_chat_messages(session_id, id);

CREATE TABLE triage_chat_actions (
    id           INTEGER PRIMARY KEY,
    message_id   INTEGER REFERENCES triage_chat_messages(id) ON DELETE SET NULL,
    commanded_by INTEGER REFERENCES users(id),     -- de opdrachtgever (mens)
    verb         TEXT NOT NULL,
    project_id   INTEGER REFERENCES projects(id),
    params       TEXT NOT NULL,                     -- JSON
    target_refs  TEXT NOT NULL,                     -- JSON-lijst van geraakte refs
    executed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
