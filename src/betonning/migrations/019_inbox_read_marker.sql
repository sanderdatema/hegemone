-- BETON-55: mention-inbox read-marker per user.
-- Elke user houdt bij tot welk event-id hij zijn inbox gelezen heeft; alles met
-- een hoger id dat hem raakt (mention, toewijzing, comment op zijn item) telt als
-- ongelezen. Default 0 = alles ongelezen tot het eerste "gezien"-signaal.
-- Migratierunner zet PRAGMA user_version = 19 na succes.

ALTER TABLE users ADD COLUMN last_seen_event_id INTEGER NOT NULL DEFAULT 0;
