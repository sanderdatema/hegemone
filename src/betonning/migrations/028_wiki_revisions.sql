-- BETON-209: edit-history voor wiki-pagina's. Elke schrijf (create/update door de
-- mens via de UI, door een agent via MCP set_memory, of door de wiki-compiler-bot)
-- legt een onveranderlijke snapshot van titel + body vast, plus wie en wanneer.
-- De timeline naast een pagina toont die revisies; een diff en restore hangen
-- eraan. `author_id` is nullable (SET NULL bij soft-delete valt buiten scope, maar
-- de backfill-revisies hieronder hebben geen bekende auteur → NULL).
-- Migratierunner zet PRAGMA user_version = 28 na succes.

CREATE TABLE wiki_revisions (
    id          INTEGER PRIMARY KEY,
    page_id     INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    body_md     TEXT NOT NULL DEFAULT '',
    author_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- NULL = onbekend
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_wiki_revisions_page ON wiki_revisions(page_id, created_at);

-- Backfill: geef elke bestaande pagina één begin-revisie (auteur onbekend,
-- tijdstip = laatste wijziging) zodat de timeline nooit leeg is voor pagina's
-- die vóór deze feature bestonden.
INSERT INTO wiki_revisions (page_id, title, body_md, author_id, created_at)
SELECT id, title, body_md, NULL, updated_at FROM wiki_pages;
