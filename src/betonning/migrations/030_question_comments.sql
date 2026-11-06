-- BETON-219: vraagmodule. Een comment kan een speciaal type 'question' zijn,
-- optioneel met meerkeuze-opties. Iemand (meestal de mens) beantwoordt met één
-- klik of vrije tekst; het antwoord is zelf een gewoon comment op hetzelfde item,
-- gelinkt aan de vraag via answer_comment_id.
--
-- Bewust ADD COLUMN (geen table-recreate): een table-recreate breekt FK's op de
-- gevulde prod-DB. Een kolom-CHECK bij ADD COLUMN mag in SQLite (tabel-CHECK niet);
-- de REFERENCES-kolommen mogen omdat hun default NULL is.
ALTER TABLE comments ADD COLUMN kind TEXT NOT NULL DEFAULT 'comment'
    CHECK (kind IN ('comment', 'question'));
-- JSON-array van strings; NULL tenzij het een question met opties is.
ALTER TABLE comments ADD COLUMN question_options TEXT;
-- Antwoord-metadata op de vraag zelf (NULL zolang onbeantwoord).
ALTER TABLE comments ADD COLUMN answered_at TEXT;
ALTER TABLE comments ADD COLUMN answered_by INTEGER REFERENCES users(id);
ALTER TABLE comments ADD COLUMN answer_comment_id INTEGER REFERENCES comments(id);
