-- Fase 3 (BETON-10) — expliciete "gesloten"-status per state.
-- Gesloten kolommen (Done, Cancelled) worden in de UI ingeklapt/gedempt en
-- tellen niet als "open". Expliciet veld (niet afgeleid van group) zodat het per
-- state via de states-API te zetten is. Backfill: bestaande completed/cancelled-
-- states sluiten, zodat ook gemigreerde projecten meteen correct gedrag hebben.
-- Migratierunner zet PRAGMA user_version = 6 na succes.

ALTER TABLE states ADD COLUMN closed INTEGER NOT NULL DEFAULT 0;

UPDATE states SET closed = 1 WHERE grp IN ('completed', 'cancelled');
