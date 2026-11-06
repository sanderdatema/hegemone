-- BETON-454: een agent kan een eigen vraag intrekken (het antwoord kwam elders,
-- bv. in de chat). Een ingetrokken vraag is niet beantwoord én niet meer open.
-- Nullable TEXT zonder default; NULL = niet ingetrokken. ADD COLUMN, dus geen
-- table-recreate op de gevulde prod-db.
ALTER TABLE comments ADD COLUMN withdrawn_at TEXT;
ALTER TABLE comments ADD COLUMN withdrawn_reason TEXT;
