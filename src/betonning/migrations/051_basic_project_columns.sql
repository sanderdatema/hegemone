-- BETON-511: vereenvoudig alleen een opgeslagen oude standaardtemplate.
-- Bestaande projecten en afwijkende, bewust aangepaste templates blijven intact.
UPDATE project_template SET states_json = (
    SELECT json_group_array(json(value)) FROM (
        SELECT value FROM json_each(project_template.states_json)
        WHERE json_extract(value, '$.name') NOT IN ('triage', 'blocked', 'review')
        ORDER BY CASE json_extract(value, '$.name')
            WHEN 'backlog' THEN 0 WHEN 'todo' THEN 1 WHEN 'in-progress' THEN 2
            WHEN 'deferred' THEN 3 WHEN 'done' THEN 4 WHEN 'cancelled' THEN 5 END
    )
)
WHERE json_array_length(states_json) = 9
AND (SELECT count(DISTINCT json_extract(value, '$.name')) FROM json_each(states_json)
     WHERE json_extract(value, '$.name') IN
     ('backlog','triage','todo','in-progress','blocked','review','done','cancelled','deferred')) = 9;
