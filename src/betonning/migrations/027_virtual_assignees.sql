-- BETON-207: virtuele toewijzing. Triage/decompose wijzen coding-werk niet meer
-- direct toe aan een concrete coding-agent (claude/codex/zcode), maar aan de
-- virtuele assignee `coding-agent` — een gedeelde queue die door élke coding-
-- agent opgepakt mag worden. Voor Hermes komt er een virtuele `hermes` waar
-- triage naar toewijst als geen enkele specifieke Hermes-agent duidelijk past.
--
-- `is_virtual` markeert deze pseudo-agents zodat ze buiten de "echte agent"-
-- logica vallen (coding_agent_handles, het access-overzicht) maar wél gewoon
-- toewijsbaar zijn (items.assignee_id → users.id). ADD COLUMN is FK-veilig; een
-- table-recreate zou op de gevulde prod-DB breken (zie migratie 022).
-- Migratierunner zet PRAGMA user_version = 27 na succes.

ALTER TABLE users ADD COLUMN is_virtual INTEGER NOT NULL DEFAULT 0;

-- Seed de twee virtuele assignees. Idempotent (WHERE NOT EXISTS) zodat de
-- migratie op een DB waar ze al bestaan niet op de UNIQUE-handle breekt.
-- api_key_hash is NOT NULL UNIQUE: een sentinel die nooit de sha256-hex van een
-- echte key kan zijn (64 hex-tekens) — deze agents authenticeren nooit.
INSERT INTO users (handle, display_name, kind, agent_type, description,
                   api_key_hash, is_virtual)
SELECT 'coding-agent', 'Coding Agent', 'agent', 'coding',
    'Virtuele toewijzing voor de algemene coding-queue. Tickets met deze '
    || 'assignee mogen door Claude, Codex, zcode en andere coding-agents '
    || 'opgepakt worden.',
    'virtual:coding-agent', 1
WHERE NOT EXISTS (SELECT 1 FROM users WHERE handle = 'coding-agent');

-- Handle `hermes-agent` (niet `hermes`) — spiegelt `coding-agent` en botst niet
-- met de agent_type 'hermes'. Display-naam blijft "Hermes".
INSERT INTO users (handle, display_name, kind, agent_type, description,
                   api_key_hash, is_virtual)
SELECT 'hermes-agent', 'Hermes', 'agent', 'hermes',
    'Virtuele toewijzing voor het Hermes-team wanneer triage niet eenduidig '
    || 'één specifieke Hermes-agent kan kiezen.',
    'virtual:hermes-agent', 1
WHERE NOT EXISTS (SELECT 1 FROM users WHERE handle = 'hermes-agent');
