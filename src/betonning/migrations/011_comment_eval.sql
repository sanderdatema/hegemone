-- Triage-bot fase 2 (BETON-22) — comment-evaluatie-marker.
-- `evaluated_at` markeert of de triage-bot een comment al heeft beoordeeld
-- (NULL = nog niet), zodat de loop idempotent is en debounce kan toepassen.
-- Migratierunner zet PRAGMA user_version = 11 na succes.

ALTER TABLE comments ADD COLUMN evaluated_at TEXT;

CREATE INDEX idx_comments_evaluated ON comments(evaluated_at);

-- Bestaande comments dateren van vóór fase 2: markeer ze als al-beoordeeld zodat
-- het aanzetten van de bot geen historische comments (her)beoordeelt. Alleen
-- níeuwe comments (evaluated_at NULL) worden voortaan verwerkt.
UPDATE comments SET evaluated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
