-- BETON-123: per-project agent-toegangsniveaus (none/respond/assign).
--
-- Twee uitzonderingstabellen: geen rij = val door naar de laag eronder. Het
-- effectieve niveau voor (project, agent) = per-agent override ?? per-type
-- default ?? globale default 'assign'. Zo blijft de bestaande situatie
-- (volledige deelname) intact zonder data-migratie, en geldt een type-regel
-- (bv. 'hermes → none op BETON') automatisch ook voor toekomstige agents.
--
-- Pure CREATE TABLE (geen table-recreate) → FK-veilig op een gevulde DB.
-- De ordening none < respond < assign zit in de code, niet in SQL.
-- Migratierunner zet PRAGMA user_version = 23 na succes.

CREATE TABLE project_agent_type_access (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_type TEXT    NOT NULL,               -- 'coding' | 'hermes'
    level      TEXT    NOT NULL CHECK (level IN ('none', 'respond', 'assign')),
    PRIMARY KEY (project_id, agent_type)
);

CREATE TABLE project_agent_access (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    level      TEXT    NOT NULL CHECK (level IN ('none', 'respond', 'assign')),
    PRIMARY KEY (project_id, user_id)
);
