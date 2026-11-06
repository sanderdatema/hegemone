-- Fase triage-bot (BETON-22) — marker + embeddings-store.
-- `triaged_at` markeert of de ingebouwde triage-bot een item al heeft verwerkt
-- (NULL = nog niet), zodat de triage-loop idempotent is. `item_embeddings` bewaart
-- per item één vector (float32-blob) voor dedup via cosine-similarity.
-- Migratierunner zet PRAGMA user_version = 8 na succes.

ALTER TABLE items ADD COLUMN triaged_at TEXT;

CREATE INDEX idx_items_triaged ON items(triaged_at);

-- Bestaande items dateren van vóór de bot: markeer ze als al-getriaged zodat het
-- aanzetten van de bot niet de hele backlog (her)triaged. Alleen níeuwe items
-- (triaged_at NULL) worden voortaan verwerkt; backfill van oude items is een
-- aparte, opt-in stap (fase 3).
UPDATE items SET triaged_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

CREATE TABLE item_embeddings (
    item_id     INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    dims        INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
