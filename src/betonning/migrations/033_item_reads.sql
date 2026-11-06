-- BETON-294: per-item read-state. Tot nu toe kende Betonning maar één begrip van
-- "gelezen": de globale watermark per user (`users.last_seen_event_id`, migratie
-- 019), die `inbox.mark_seen` alleen kan ophogen. Daarmee zou één ticket openen
-- álles als gelezen markeren — onbruikbaar voor een per-kaart-markering
-- (BETON-281) of "ticket openen = deze notificaties gelezen" (BETON-286).
--
-- Deze tabel zet een watermark náást de globale: per (user, item) tot welk
-- event-id die user dit item gezien heeft. Een item is gelezen als zijn hoogste
-- vreemde event-id onder de globale óf de per-item-watermark ligt — zo blijft
-- het bestaande inboxgedrag intact en komt het per-item-gedrag erbovenop.
--
-- Nieuwe tabel (geen table-recreate) → FK-veilig op de gevulde prod-DB; een
-- table-recreate slaagt op een lege test-DB en breekt op prod.
CREATE TABLE item_reads (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    last_seen_event_id INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (user_id, item_id)
);
