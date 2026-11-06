-- BETON-265/263: het antwoord op een vraag is niet langer een los comment maar
-- inline-metadata op de vraag-comment zelf. Zo verschijnt het antwoord niet meer
-- "rommelig" als apart comment in de tijdlijn (265), kan het gewijzigd worden tot
-- de notificatie verstuurd is (263), en pikt de triage-bot het niet op als comment
-- (260).
--
-- Bewust ADD COLUMN (geen table-recreate): dat breekt FK's op de gevulde prod-DB.
-- De bestaande kind-CHECK ('comment','question') blijft ongewijzigd — we voeren
-- géén nieuw kind 'answer' in (dat zou een table-recreate vergen). Oude
-- antwoord-comments blijven bestaan als kind='comment' en worden overal gefilterd
-- via hun answer_comment_id-koppeling.
ALTER TABLE comments ADD COLUMN answer_text TEXT;
-- Index van de gekozen optie (NULL bij een vrijtekst-antwoord of onbeantwoord).
ALTER TABLE comments ADD COLUMN answer_option_index INTEGER;

-- Backfill: kopieer voor reeds beantwoorde vragen de tekst van het gekoppelde
-- antwoord-comment naar answer_text, zodat het inline gerenderd kan worden en de
-- oude antwoord-comment uit de tijdlijn gefilterd kan worden.
UPDATE comments AS q
   SET answer_text = (
       SELECT a.body_md FROM comments AS a WHERE a.id = q.answer_comment_id
   )
 WHERE q.kind = 'question'
   AND q.answer_comment_id IS NOT NULL
   AND q.answer_text IS NULL;
