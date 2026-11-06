-- BETON-338: bewaar de comment die op de noodstop stuitte.
--
-- De comment die het slot TRIGGERT gaat er al in (BETON-302: de tiende gaat er
-- nog in, dán valt het slot). Wat verloren ging is de EERSTVOLGENDE: de agent
-- die ná het slot reageert en een 409 krijgt. Die tekst is nu weg — terwijl
-- juist die vaak zegt waaróm de lus doorging.
--
-- Eén wachtplek per item (UNIQUE op item_id). De limiet zit bewust in de
-- constraint en niet in applicatielogica: twee gelijktijdige geblokkeerde
-- verzoeken kunnen zo niet allebei een rij maken — de tweede krijgt een
-- IntegrityError die de API omzet naar "er staat al een bericht in de wacht".
-- Geen race-window.
--
-- Waarom een aparte tabel en geen `comments.held_at`: een held comment is nog
-- géén comment. Zou hij in `comments` staan, dan moet élke bestaande query hem
-- uitsluiten — count_for_item, de tijdlijn, de fanout, de drie
-- triage-poll-queries, de dedup. Eén vergeten WHERE en een niet-geplaatste
-- comment lekt als echte comment, of erger: telt mee voor de drempel en houdt
-- het slot in stand.
--
-- CREATE TABLE (geen wijziging aan de gevulde `items`/`comments`): veilig op
-- prod, zie de header van 034_triage_assign_trigger.sql.
CREATE TABLE held_comments (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL REFERENCES users(id),
    body_md    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
