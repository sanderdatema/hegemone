-- BETON-39: uitgestelde items (deferred_until).
-- Een item dat op iets moet wachten hoort niet in een actieve kolom te blijven
-- staan. `deferred_until` (ISO-datum, nullable) markeert tot wanneer het item met
-- rust gelaten wordt; het item gaat dan naar de `deferred`-state. Een lichte
-- periodieke check (repo.items.reactivate_deferred) zet verlopen items terug naar
-- de actieve `todo`/default-state en wist het veld.
-- Migratierunner zet PRAGMA user_version = 17 na succes.

ALTER TABLE items ADD COLUMN deferred_until TEXT;
