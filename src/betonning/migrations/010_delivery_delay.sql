-- Trigger-delay + annulering (BETON-18).
-- Een delivery wordt pas ná een korte wachttijd (not_before) verzendbaar, zodat
-- een snel teruggedraaide actie (bv. een verwijderde comment) de agent niet
-- meer triggert. Bij het vuurmoment checkt de dispatcher of de aanleiding nog
-- bestaat; zo niet, dan krijgt de delivery de nieuwe status 'cancelled'.
--
-- De status-CHECK kende alleen pending/delivered/failed, dus de tabel wordt
-- herbouwd (SQLite kan een CHECK niet los wijzigen). Niets verwijst naar
-- webhook_deliveries, dus een simpele recreate volstaat.
-- Migratierunner zet PRAGMA user_version = 10 na succes.

CREATE TABLE webhook_deliveries_new (
    id            INTEGER PRIMARY KEY,
    event_id      INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'delivered', 'failed', 'cancelled')),
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    next_retry_at TEXT,
    not_before    TEXT,
    channel       TEXT NOT NULL DEFAULT 'webhook',
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

INSERT INTO webhook_deliveries_new
    (id, event_id, user_id, status, attempts, last_error, next_retry_at, channel, created_at)
SELECT id, event_id, user_id, status, attempts, last_error, next_retry_at, channel, created_at
FROM webhook_deliveries;

DROP TABLE webhook_deliveries;
ALTER TABLE webhook_deliveries_new RENAME TO webhook_deliveries;

CREATE INDEX idx_deliveries_status ON webhook_deliveries(status);
