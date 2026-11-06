-- BETON-199: een item dat naar deferred gaat, moet op de deferred-datum terug
-- naar de state waar het vandaan kwam (niet blind naar todo/default). Als een
-- item rechtstreeks in deferred is aangemaakt (geen vorige state), blijft de
-- bestaande todo/default-fallback gelden.
-- Migratierunner zet PRAGMA user_version = 26 na succes.

ALTER TABLE items ADD COLUMN deferred_from_state_id INTEGER REFERENCES states(id);
