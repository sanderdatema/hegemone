-- Existing and new projects retain automatic comment-limit locks by default.
ALTER TABLE projects ADD COLUMN auto_lock_enabled INTEGER NOT NULL DEFAULT 1
    CHECK (auto_lock_enabled IN (0, 1));

-- A restore must not change the new safety setting in the same write.
DROP TRIGGER archived_projects_update;
CREATE TRIGGER archived_projects_update
BEFORE UPDATE ON projects
WHEN OLD.archived_at IS NOT NULL AND (
    NEW.archived_at IS NOT NULL OR
    NEW.id IS NOT OLD.id OR
    NEW.key IS NOT OLD.key OR
    NEW.name IS NOT OLD.name OR
    NEW.description IS NOT OLD.description OR
    NEW.next_seq IS NOT OLD.next_seq OR
    NEW.created_at IS NOT OLD.created_at OR
    NEW.triage_enabled IS NOT OLD.triage_enabled OR
    NEW.wiki_compile_enabled IS NOT OLD.wiki_compile_enabled OR
    NEW.auto_lock_enabled IS NOT OLD.auto_lock_enabled
)
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;
