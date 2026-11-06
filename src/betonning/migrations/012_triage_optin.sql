-- Triage-bot fase 3 (BETON-22) — per-project opt-in.
-- `triage_enabled` bepaalt of de ingebouwde triage-bot een project verwerkt
-- (0 = uit, default). Zo wordt niet elk project automatisch getriaged; opt-in
-- gaat per project via de API/CLI.
-- Migratierunner zet PRAGMA user_version = 12 na succes.

ALTER TABLE projects ADD COLUMN triage_enabled INTEGER NOT NULL DEFAULT 0;
