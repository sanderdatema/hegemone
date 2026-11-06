-- BETON-476: modellabels worden werkklassen. Per project: opus/gpt-5.5/sol ->
-- complex, sonnet -> standaard, gpt-5.4-mini/terra -> routine.
-- Bestaat het doellabel in het project al, dan worden de koppelingen
-- (item_labels + de twee guardrail-scope-tabellen) samengevoegd en het oude label
-- verwijderd; anders wordt het label in-place hernoemd (behoudt kleur en koppelingen).
-- Alleen data-updates, geen schemawijziging.

-- opus -> complex
UPDATE labels SET name = 'complex' WHERE name = 'opus'
  AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.project_id = labels.project_id AND t.name = 'complex');
INSERT OR IGNORE INTO item_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'opus'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'opus');
INSERT OR IGNORE INTO item_guardrail_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'opus'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_guardrail_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'opus');
INSERT OR IGNORE INTO item_guardrail_proposal_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_proposal_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'opus'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_guardrail_proposal_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'opus');
DELETE FROM labels WHERE name = 'opus';

-- sonnet -> standaard
UPDATE labels SET name = 'standaard' WHERE name = 'sonnet'
  AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.project_id = labels.project_id AND t.name = 'standaard');
INSERT OR IGNORE INTO item_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'sonnet'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'standaard';
DELETE FROM item_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'sonnet');
INSERT OR IGNORE INTO item_guardrail_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'sonnet'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'standaard';
DELETE FROM item_guardrail_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'sonnet');
INSERT OR IGNORE INTO item_guardrail_proposal_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_proposal_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'sonnet'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'standaard';
DELETE FROM item_guardrail_proposal_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'sonnet');
DELETE FROM labels WHERE name = 'sonnet';

-- gpt-5.5 -> complex
UPDATE labels SET name = 'complex' WHERE name = 'gpt-5.5'
  AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.project_id = labels.project_id AND t.name = 'complex');
INSERT OR IGNORE INTO item_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'gpt-5.5'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'gpt-5.5');
INSERT OR IGNORE INTO item_guardrail_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'gpt-5.5'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_guardrail_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'gpt-5.5');
INSERT OR IGNORE INTO item_guardrail_proposal_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_proposal_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'gpt-5.5'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_guardrail_proposal_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'gpt-5.5');
DELETE FROM labels WHERE name = 'gpt-5.5';

-- gpt-5.4-mini -> routine
UPDATE labels SET name = 'routine' WHERE name = 'gpt-5.4-mini'
  AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.project_id = labels.project_id AND t.name = 'routine');
INSERT OR IGNORE INTO item_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'gpt-5.4-mini'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'routine';
DELETE FROM item_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'gpt-5.4-mini');
INSERT OR IGNORE INTO item_guardrail_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'gpt-5.4-mini'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'routine';
DELETE FROM item_guardrail_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'gpt-5.4-mini');
INSERT OR IGNORE INTO item_guardrail_proposal_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_proposal_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'gpt-5.4-mini'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'routine';
DELETE FROM item_guardrail_proposal_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'gpt-5.4-mini');
DELETE FROM labels WHERE name = 'gpt-5.4-mini';

-- sol -> complex
UPDATE labels SET name = 'complex' WHERE name = 'sol'
  AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.project_id = labels.project_id AND t.name = 'complex');
INSERT OR IGNORE INTO item_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'sol'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'sol');
INSERT OR IGNORE INTO item_guardrail_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'sol'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_guardrail_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'sol');
INSERT OR IGNORE INTO item_guardrail_proposal_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_proposal_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'sol'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'complex';
DELETE FROM item_guardrail_proposal_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'sol');
DELETE FROM labels WHERE name = 'sol';

-- terra -> routine
UPDATE labels SET name = 'routine' WHERE name = 'terra'
  AND NOT EXISTS (SELECT 1 FROM labels t WHERE t.project_id = labels.project_id AND t.name = 'routine');
INSERT OR IGNORE INTO item_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'terra'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'routine';
DELETE FROM item_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'terra');
INSERT OR IGNORE INTO item_guardrail_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'terra'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'routine';
DELETE FROM item_guardrail_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'terra');
INSERT OR IGNORE INTO item_guardrail_proposal_labels (item_id, label_id)
  SELECT x.item_id, tgt.id FROM item_guardrail_proposal_labels x JOIN labels o ON o.id = x.label_id AND o.name = 'terra'
  JOIN labels tgt ON tgt.project_id = o.project_id AND tgt.name = 'routine';
DELETE FROM item_guardrail_proposal_labels WHERE label_id IN (SELECT id FROM labels WHERE name = 'terra');
DELETE FROM labels WHERE name = 'terra';
