-- Fase E — Telegram-notificaties naast webhooks.
-- users.telegram_chat_id: waar @mentions/toewijzingen heen gepusht worden
--   (onafhankelijk van webhook_url; beide kanalen zijn apart configureerbaar).
-- webhook_deliveries.channel: 'webhook' (default, bestaand gedrag) of 'telegram'.
-- Migratierunner zet PRAGMA user_version = 3 na succes.

ALTER TABLE users ADD COLUMN telegram_chat_id TEXT;

ALTER TABLE webhook_deliveries ADD COLUMN channel TEXT NOT NULL DEFAULT 'webhook';
