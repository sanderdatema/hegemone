-- BETON-510: vul ontbrekende werkklassen aan, behoud bestaande kleuren/koppelingen.
INSERT INTO labels (project_id, name, color)
SELECT p.id, c.name, '#95a5a6' FROM projects p
CROSS JOIN (SELECT 'routine' AS name UNION ALL SELECT 'standaard' UNION ALL SELECT 'complex') c
WHERE NOT EXISTS (
    SELECT 1 FROM labels l WHERE l.project_id = p.id AND l.name = c.name COLLATE NOCASE
);
