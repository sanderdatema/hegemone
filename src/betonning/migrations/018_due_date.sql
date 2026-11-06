-- BETON-53: einddatum (due_date) op items.
-- Een item kan een streefdatum krijgen zodat de UI overdue/vandaag kan markeren
-- en er op `due_before` gefilterd kan worden. ISO-datum (YYYY-MM-DD), nullable —
-- géén automatische state-flip (anders dan deferred_until): puur informatief +
-- filterbaar. Migratierunner zet PRAGMA user_version = 18 na succes.

ALTER TABLE items ADD COLUMN due_date TEXT;
