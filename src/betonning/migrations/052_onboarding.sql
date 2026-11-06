-- Eerste-installatiewizard geldt alleen voor de via setup aangemaakte beheerder.
CREATE TABLE onboarding (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    step TEXT NOT NULL DEFAULT 'project' CHECK (step IN ('project', 'agents', 'complete')),
    locale TEXT NOT NULL DEFAULT 'en' CHECK (locale IN ('en', 'nl')),
    project_key TEXT
);
