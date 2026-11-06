-- BETON-490: één aanpasbare kolomtemplate voor toekomstige projecten.
CREATE TABLE project_template (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    states_json TEXT NOT NULL
);
