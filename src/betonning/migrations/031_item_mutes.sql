-- BETON-245: per-item mute. Een user kan zich afmelden voor de fanout van één
-- item; hij valt dan uit de afgeleide subscribers-union (assignee, eerdere
-- participants, subscribe_all) zonder dat er verder iets aan de afleiding
-- verandert. Nieuwe tabel (geen table-recreate) → FK-veilig op de gevulde prod-DB.
CREATE TABLE item_mutes (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (item_id, user_id)
);
