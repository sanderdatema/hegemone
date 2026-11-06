-- BETON-302: noodstop op tickets — een ticket kan "op slot" (agents zwijgen).
--
-- Twee kolommen, want een boolean volstaat niet. "Na ontgrendelen weer 5
-- comments ruimte" betekent dat de drempel MEEVERSCHUIFT: een vaste 10 zou een
-- item dat bij 10 ontgrendeld wordt meteen weer dichtklappen. Vandaar een
-- resetbare drempel naast de slot-vlag zelf:
--
--   locked_at     -- NULL = open, timestamp = op slot
--   comment_limit -- aantal comments waarbij hij (opnieuw) dichtklapt
--
-- Ontgrendelen zet `locked_at = NULL` én `comment_limit = <huidige count> + 5`.
--
-- ADD COLUMN (geen table-recreate): draait zo ook op een gevulde prod-db zonder
-- de FK's te breken — zie de header van 034_triage_assign_trigger.sql.
ALTER TABLE items ADD COLUMN locked_at TEXT;
ALTER TABLE items ADD COLUMN comment_limit INTEGER NOT NULL DEFAULT 10;
