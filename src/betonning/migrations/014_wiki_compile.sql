-- Wiki-compiler (BETON-24, Karpathy's ingestion-loop) — marker + per-project opt-in.
-- Wanneer een ticket op een closed-state (done/cancelled) komt, compileert een
-- LLM-loop de duurzame lessen uit het ticket + z'n comments naar de projectwiki.
-- `wiki_compiled_at` markeert of een item al gecompileerd is (NULL = nog niet).
-- `wiki_compile_enabled` is de per-project opt-in (los van triage). Standaard uit.
-- Migratierunner zet PRAGMA user_version = 14 na succes.

ALTER TABLE items ADD COLUMN wiki_compiled_at TEXT;
CREATE INDEX idx_items_wiki_compiled ON items(wiki_compiled_at);

ALTER TABLE projects ADD COLUMN wiki_compile_enabled INTEGER NOT NULL DEFAULT 0;

-- Bestaande items dateren van vóór de compiler: markeer ze als al-gecompileerd
-- zodat aanzetten niet de hele historie herverwerkt. Backfill is een aparte,
-- opt-in stap (net als bij de triage-bot).
UPDATE items SET wiki_compiled_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now');
