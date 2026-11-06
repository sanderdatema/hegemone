-- BETON-1 — projecten archiveren i.p.v. hard verwijderen.
-- Gearchiveerde projecten blijven bestaan (items/history/refs blijven geldig) maar
-- vallen uit de projectenlijst tenzij expliciet opgevraagd (?archived=true).
-- Migratierunner zet PRAGMA user_version = 4 na succes.

ALTER TABLE projects ADD COLUMN archived_at TEXT;

CREATE INDEX idx_projects_archived ON projects(archived_at);
