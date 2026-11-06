-- BETON-468: virtuele queues (is_virtual = 1) authenticeren nooit. Op prod had
-- coding-agent toch een echte key-hash (73 events geschreven met die key), dus
-- attributie viel weg. De lookup-poort (`get_by_api_key`: is_virtual = 0) is de
-- eigenlijke afdichting; dit zet de sentinel van migratie 027 terug.
-- api_key_hash is NOT NULL UNIQUE, dus een sentinel i.p.v. NULL; 'virtual:<handle>'
-- is geen 64-hex-sha256 en dus nooit het resultaat van hash_api_key().
UPDATE users SET api_key_hash = 'virtual:' || handle WHERE is_virtual = 1;
