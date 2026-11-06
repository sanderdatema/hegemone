-- BETON-369: een mens kan een ticket expliciet VOLGEN. Tot nu toe was de
-- subscribers-doelgroep volledig afgeleid (assignee + eerdere participants +
-- subscribe_all), met `item_mutes` (migratie 031) als enige afmeld-knop. Er was
-- geen aanmeld-knop: een ticket waar je niets mee deed maar wél op wilde letten
-- kon je alleen volgen door er een comment onder te zetten — wat een notificatie
-- naar iedereen stuurt en de agents aan het werk zet.
--
-- Deze tabel is de tegenhanger van `item_mutes`: dezelfde vorm, omgekeerd teken.
-- Volgen voegt je toe aan de fanout-doelgroep en levert de inbox-reden
-- "following"; muten haalt je eruit. Muten wint (het filter draait ná de union).
--
-- Nieuwe tabel (geen table-recreate) → FK-veilig op de gevulde prod-DB.
CREATE TABLE item_follows (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (user_id, item_id)
);
