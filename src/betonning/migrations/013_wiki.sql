-- LLM-wiki / memory-provider (BETON-24), geïnspireerd op Karpathy's LLM Wiki:
-- een persistente, (agent-)onderhouden markdown-kennisbank die agents als context
-- inladen i.p.v. per-query her-ophalen. Twee niveaus: globaal (project_id NULL,
-- voor álle projecten/agents) en per project. Pagina's linken met [[slug]].
-- Migratierunner zet PRAGMA user_version = 13 na succes.

CREATE TABLE wiki_pages (
    id          INTEGER PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,  -- NULL = globaal
    slug        TEXT NOT NULL,
    title       TEXT NOT NULL,
    body_md     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Slug is uniek per scope. Twee partiële indexen omdat SQLite NULL-project_id's
-- in een gewone UNIQUE als verschillend zou behandelen (dan konden er meerdere
-- globale pagina's met dezelfde slug bestaan).
CREATE UNIQUE INDEX idx_wiki_slug_global
    ON wiki_pages(slug) WHERE project_id IS NULL;
CREATE UNIQUE INDEX idx_wiki_slug_project
    ON wiki_pages(project_id, slug) WHERE project_id IS NOT NULL;
