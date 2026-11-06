-- BETON-72: vrije-tekst omschrijving per user/agent (doel/expertise).
-- Voedt de agent-beheerpagina én de expertise-routering van triage/decompose
-- (BETON-67): de roster (handle + description) gaat mee in de LLM-context zodat
-- een item naar de best passende agent wordt gerouteerd.
-- Migratierunner zet PRAGMA user_version = 20 na succes.

ALTER TABLE users ADD COLUMN description TEXT;
