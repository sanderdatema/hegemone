-- Dubbele/zinloze relaties opruimen (BETON-20).
-- `relates_to` is symmetrisch: A→B en B→A hoorden hetzelfde te betekenen, maar
-- werden als twee losse rijen opgeslagen waardoor de relatie dubbel getoond werd.
-- Voortaan slaan we symmetrische relaties canoniek op (item_id < related_item_id,
-- zie repo/relations.py) zodat de bestaande UNIQUE-constraint duplicaten weert.
-- Deze migratie saneert de reeds aanwezige data.
-- Migratierunner zet PRAGMA user_version = 9 na succes.

-- 1. Zinloze self-relaties (item verwijst naar zichzelf) weg.
DELETE FROM relations WHERE item_id = related_item_id;

-- 2. Verwijder de niet-canonieke helft daar waar beide richtingen van een
--    symmetrische relatie bestaan (houd de rij met item_id < related_item_id).
DELETE FROM relations
WHERE type = 'relates_to'
  AND item_id > related_item_id
  AND EXISTS (
    SELECT 1 FROM relations r2
    WHERE r2.type = 'relates_to'
      AND r2.item_id = relations.related_item_id
      AND r2.related_item_id = relations.item_id
  );

-- 3. Canonicaliseer de resterende losse symmetrische relaties naar min→max.
--    Na stap 2 bestaat de omgekeerde canonieke rij niet meer, dus deze flip
--    kan de UNIQUE-constraint niet schenden.
UPDATE relations
SET item_id = related_item_id, related_item_id = item_id
WHERE type = 'relates_to' AND item_id > related_item_id;
