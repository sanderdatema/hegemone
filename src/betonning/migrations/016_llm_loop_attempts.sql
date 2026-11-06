-- Poison-item-quarantaine voor de LLM-achtergrondloops (BETON-41).
-- De triage-, comment-eval- en wiki-compile-loops hadden geen begrenzing op
-- mislukkingen: een exception uit llm.complete/embeddings.embed liet het item/
-- de comment ongemarkeerd, waardoor het elke cyclus opnieuw werd geprobeerd (en
-- de rest van de batch blokkeerde). Deze kolommen tellen mislukte pogingen; na
-- N pogingen slaan de finders het item/de comment over (quarantaine). Gemodelleerd
-- naar het webhook-subsysteem (attempts + terminal state).
-- Migratierunner zet PRAGMA user_version = 16 na succes.

ALTER TABLE items ADD COLUMN triage_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE items ADD COLUMN triage_error_at TEXT;

ALTER TABLE items ADD COLUMN wiki_compile_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE items ADD COLUMN wiki_compile_error_at TEXT;

ALTER TABLE comments ADD COLUMN eval_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE comments ADD COLUMN eval_error_at TEXT;
