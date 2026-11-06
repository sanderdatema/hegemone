-- BETON-420: guardrail op een ticket. Kennis die niet in een regressietest past
-- ("prompts voor model X kort houden, anders degradeert het") en die elke agent
-- hierna moet naleven. Eén tekstveld: de tekst is tegelijk de verplichte uitleg
-- (wat, waarom, wat te doen/laten) én de payload die de agent krijgt.
--
-- ACTIEF = tekst aanwezig, niet opgeheven, ticket niet gearchiveerd. Die derde
-- term is bewust: archiveren geeft de plek in het plafond van vijf projectbrede
-- guardrails vrij in plaats van hem door een dood ticket te laten bezetten. De
-- definitie staat als SQL-fragment in `repo/items.py:GUARDRAIL_ACTIVE`.
--
-- `guardrail_review_by` (ISO-datum) is verplicht zodra de guardrail actief is:
-- een guardrail kost elke agent tokens, elke ronde, dus de vraag "geldt dit
-- nog?" moet vanzelf terugkomen. `guardrail_review_asked_at` is de
-- idempotentie-marker van die reviewvraag — hij wordt NA het plaatsen van de
-- vraag gezet (dezelfde valkuil die 039_item_stale.sql documenteert) en gaat
-- weer op NULL zodra er een nieuwe reviewdatum staat.
--
-- De `1000` in de CHECK dupliceert `models.GUARDRAIL_MAX_CHARS`. Dat is bewust:
-- een migratie is onveranderlijk en mag niet meebewegen met een constante.
--
-- ADD COLUMN, geen table-recreate: een recreate breekt FK's op de gevulde
-- prod-db. Een kolom-CHECK bij ADD COLUMN mag in SQLite (tabel-CHECK niet);
-- de REFERENCES-kolom mag omdat hij nullable is en geen default heeft.
ALTER TABLE items ADD COLUMN guardrail_md TEXT
    CHECK (guardrail_md IS NULL OR length(guardrail_md) <= 1000);
ALTER TABLE items ADD COLUMN guardrail_review_by TEXT;
ALTER TABLE items ADD COLUMN guardrail_set_by INTEGER REFERENCES users(id);
ALTER TABLE items ADD COLUMN guardrail_set_at TEXT;
ALTER TABLE items ADD COLUMN guardrail_lifted_at TEXT;
ALTER TABLE items ADD COLUMN guardrail_review_asked_at TEXT;

-- Scope = nul of meer projectlabels; zonder scope is de guardrail projectbreed.
-- Bewust een EIGEN tabel en niet `item_labels`: een scope-label daarin zetten
-- zou het ticket zélf herlabelen, en daar hangen bordfilters, zoek en de
-- triage-taxonomie aan. Spiegelt `item_labels` (001_initial.sql) inclusief
-- BEIDE cascades — `labels_repo.delete` is een kale DELETE FROM labels en zou
-- zonder de cascade op label_id weesrijen achterlaten.
CREATE TABLE item_guardrail_labels (
    item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, label_id)
);
