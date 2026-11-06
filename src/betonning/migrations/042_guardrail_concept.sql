-- BETON-422: een guardrail-voorstel is voortaan een CONCEPT op het ticket zelf,
-- geen vraag-comment meer. Elke wijziging door een agent — nieuw zetten, een
-- actieve guardrail wijzigen én hem opheffen — staat eerst als concept NAAST de
-- actieve versie. Tot een mens goedkeurt blijft de actieve versie de geldende.
--
-- Vandaar EIGEN opslag en géén statuskolom op de bestaande guardrail-velden:
-- concept en actief moeten tegelijk kunnen bestaan. Een aparte tabel i.p.v.
-- extra kolommen op `items`, omdat een concept ook een eigen scope-lijst draagt
-- (die kan niet in een kolom) en omdat "concept weg" dan één DELETE is die de
-- scope-rijen meeneemt — geen zes kolommen die samen op NULL moeten.
--
-- Eén concept-slot per ticket (`item_id` is PRIMARY KEY): een nieuw voorstel
-- overschrijft het openstaande. Dat is onschadelijk omdat de actieve versie
-- blijft gelden; `proposed_by` en het event leggen vast wie het laatst
-- voorstelde.
--
-- `repo/items.py:GUARDRAIL_ACTIVE` blijft ongemoeid en blijft de énige plek die
-- bezorging, plafondtelling, `has_guardrail` en de review-finder bepaalt: een
-- concept raakt de wiki-context, `applicable_guardrails`, de kaartmarkering en
-- het plafond nooit.
--
-- De `1000` in de CHECK's dupliceert `models.GUARDRAIL_MAX_CHARS`, net als in
-- 041: een migratie is onveranderlijk en mag niet meebewegen met een constante.
CREATE TABLE item_guardrail_proposals (
    item_id      INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    -- 'set'  = deze tekst/scope/reviewdatum moet de actieve versie worden;
    -- 'lift' = hef de actieve guardrail op (dan is `reason` verplicht).
    kind         TEXT NOT NULL CHECK (kind IN ('set', 'lift')),
    guardrail_md TEXT CHECK (guardrail_md IS NULL OR length(guardrail_md) <= 1000),
    review_by    TEXT,
    reason       TEXT CHECK (reason IS NULL OR length(reason) <= 1000),
    proposed_by  INTEGER REFERENCES users(id),
    proposed_at  TEXT NOT NULL
);

-- De voorgestelde scope. Spiegelt `item_guardrail_labels` (041) inclusief beide
-- cascades: `labels_repo.delete` is een kale DELETE FROM labels en zou zonder de
-- cascade op label_id weesrijen achterlaten. De cascade op het VOORSTEL (niet op
-- het item) zorgt dat een afgewezen of goedgekeurd concept zijn scope meeneemt.
CREATE TABLE item_guardrail_proposal_labels (
    item_id  INTEGER NOT NULL
             REFERENCES item_guardrail_proposals(item_id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, label_id)
);

-- Oude, nog ONBEANTWOORDE voorstel-vragen ([Guardrail-voorstel]) verliezen hun
-- afhandelaar: `_apply_guardrail_proposal_answer_if_any` verdwijnt met dit
-- ticket. Ze open laten zou ze dood maken (de mens klikt "Activeer" en er
-- gebeurt niets) en ze blijven in GET /questions?open=true hangen. Daarom hier
-- sluiten met een antwoord dat de reden noemt; de voorgestelde tekst blijft in
-- de vraagbody staan, dus een mens kan hem alsnog overnemen.
-- `evaluated_at` gaat mee vooruit: die kolom is de marker waarmee BETON-389
-- ("beantwoorde vraag alsnog door de LLM") bepaalt of er nog werk ligt.
-- `answered_by` blijft NULL: er is geen mens die dit antwoordde.
-- `substr(ltrim(body_md), 1, 20)` en niet LIKE: letterlijk vergelijken is
-- ondubbelzinnig en spiegelt het verwijderde `triage.is_guardrail_proposal`, dat op
-- `lstrip().startswith` werkt. `[Guardrail-voorstel]` is 20 tekens.
UPDATE comments
   SET answered_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
       answer_text = 'Vervallen: guardrail-voorstellen lopen sinds BETON-422 '
                     || 'als concept op het ticket zelf, niet meer via de '
                     || 'vraagmodule. De voorgestelde tekst staat hierboven.',
       evaluated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
 WHERE kind = 'question'
   AND answered_at IS NULL
   AND substr(ltrim(body_md), 1, 20) = '[Guardrail-voorstel]';
