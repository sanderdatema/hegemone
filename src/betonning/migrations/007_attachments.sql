-- Fase 4 (BETON-5) — attachments: afbeeldingen bij tickets.
-- Bytes staan op disk (content-addressed op sha256; dedup + stabiele URL); hier
-- alleen de metadata + koppeling aan project/item. Verwijderen van een item of
-- project ruimt de rijen op (ON DELETE CASCADE); de disk-bytes blijven staan
-- (gedeeld/idempotent, later evt. te GC'en).
-- Migratierunner zet PRAGMA user_version = 7 na succes.

CREATE TABLE attachments (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    item_id       INTEGER REFERENCES items(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    size          INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_attachments_item ON attachments(item_id);
CREATE INDEX idx_attachments_sha ON attachments(sha256);
