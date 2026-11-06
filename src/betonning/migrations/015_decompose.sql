-- Hidden marker voor decompose-idempotentie (BETON-31).
-- Een item met decomposed_at != NULL is al opgeknipt in subtaken en wordt nooit
-- opnieuw voorgesteld of opgeknipt. Analoog aan triaged_at/wiki_compiled_at, zodat
-- Betonning dit ook voor onderhoud kan gebruiken.
-- Migratierunner zet PRAGMA user_version = 15 na succes.

ALTER TABLE items ADD COLUMN decomposed_at TEXT;
