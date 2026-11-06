-- Uitvoeringsbeleid voor agents staat los van `closed` (UI/afgerond).
ALTER TABLE states ADD COLUMN blocks_work INTEGER NOT NULL DEFAULT 0;

-- Bestaande standaardkolommen behouden hun verwachte gedrag. Dit is alleen
-- een eenmalige migratie; daarna is de vlag per state configureerbaar.
UPDATE states
SET blocks_work = 1
WHERE name COLLATE NOCASE IN ('backlog', 'triage', 'blocked', 'deferred');
