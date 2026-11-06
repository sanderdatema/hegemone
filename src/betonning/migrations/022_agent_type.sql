-- BETON-88/82: formeel onderscheid tussen coding-agents (Claude Code, Codex)
-- en Hermes-agents (externe assistenten zoals smid). `agent_type` is NULL voor
-- mensen en voor de triage-bot; 'coding' of 'hermes' voor agents. De triage-
-- guard gebruikt dit om opus/sonnet alleen aan de Claude-coding-harnas te geven.
--
-- We voegen de kolom toe met ADD COLUMN i.p.v. een table-recreate: SQLite staat
-- een CHECK-constraint op ADD COLUMN toe zolang die alleen de nieuwe kolom en
-- constanten gebruikt. Dat is FK-veilig — een table-recreate (users droppen)
-- faalt op een gevulde DB met `FOREIGN KEY constraint failed` omdat items/
-- comments/events/webhook_deliveries naar users.id verwijzen.
-- Migratierunner zet PRAGMA user_version = 22 na succes.

-- Ruim een eventuele half-afgeronde table-recreate uit een eerdere (mislukte)
-- 022-poging op: een orphan `users_new` blijft achter als DROP TABLE users faalde.
DROP TABLE IF EXISTS users_new;

ALTER TABLE users ADD COLUMN agent_type TEXT
    CHECK (agent_type IS NULL OR agent_type IN ('coding', 'hermes'));

-- Backfill: de generieke coding-harnasen zijn bekend bij handle. Overige
-- actieve agents (behalve triage, die geen coding- of Hermes-agent is) worden
-- als Hermes-agent bestempeld.
UPDATE users SET agent_type = 'coding' WHERE handle IN ('claude', 'codex');
UPDATE users SET agent_type = 'hermes'
    WHERE kind = 'agent' AND handle NOT IN ('claude', 'codex', 'triage') AND agent_type IS NULL;
