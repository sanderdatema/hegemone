-- BETON-71: avatar-afbeelding per user/agent. Bytes staan content-addressed op
-- disk (storage.py, gedeeld met attachments); hier alleen de verwijzing: de
-- sha256 van de bytes + het content-type. Beide nullable → geen avatar valt
-- terug op de initialen-avatar in de UI. De serve-URL
-- (/api/v1/users/{handle}/avatar) is een capability-URL zonder auth zodat een
-- <img> werkt.
-- Migratierunner zet PRAGMA user_version = 21 na succes.

ALTER TABLE users ADD COLUMN avatar_sha256 TEXT;
ALTER TABLE users ADD COLUMN avatar_content_type TEXT;
