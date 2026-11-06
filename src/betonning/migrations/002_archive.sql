-- Fase B — items archiveren i.p.v. hard verwijderen.
-- Gearchiveerde items blijven bestaan (history, refs blijven geldig) maar
-- vallen uit board/list/search tenzij expliciet opgevraagd.
-- Migratierunner zet PRAGMA user_version = 2 na succes.

ALTER TABLE items ADD COLUMN archived_at TEXT;

CREATE INDEX idx_items_archived ON items(archived_at);
