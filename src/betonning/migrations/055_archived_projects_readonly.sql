-- Archived project content is immutable until an explicit project restore.
-- Guard both old and new ownership, including moves and cross-project relations.
-- RAISE(ABORT) lets the caller roll back the complete multi-write transaction.
-- Personal read receipts and delivery/audit bookkeeping remain available.

CREATE TRIGGER archived_items_insert
BEFORE INSERT ON items
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_items_update
BEFORE UPDATE ON items
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_items_delete
BEFORE DELETE ON items
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_states_insert
BEFORE INSERT ON states
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_states_update
BEFORE UPDATE ON states
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_states_delete
BEFORE DELETE ON states
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_milestones_insert
BEFORE INSERT ON milestones
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_milestones_update
BEFORE UPDATE ON milestones
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_milestones_delete
BEFORE DELETE ON milestones
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_labels_insert
BEFORE INSERT ON labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_labels_update
BEFORE UPDATE ON labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_labels_delete
BEFORE DELETE ON labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_attachments_insert
BEFORE INSERT ON attachments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_attachments_update
BEFORE UPDATE ON attachments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_attachments_delete
BEFORE DELETE ON attachments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_pages_insert
BEFORE INSERT ON wiki_pages
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_pages_update
BEFORE UPDATE ON wiki_pages
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_pages_delete
BEFORE DELETE ON wiki_pages
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_proposals_insert
BEFORE INSERT ON wiki_proposals
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_proposals_update
BEFORE UPDATE ON wiki_proposals
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_proposals_delete
BEFORE DELETE ON wiki_proposals
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_project_agent_access_insert
BEFORE INSERT ON project_agent_access
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_project_agent_access_update
BEFORE UPDATE ON project_agent_access
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_project_agent_access_delete
BEFORE DELETE ON project_agent_access
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_project_agent_type_access_insert
BEFORE INSERT ON project_agent_type_access
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_project_agent_type_access_update
BEFORE UPDATE ON project_agent_type_access
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_project_agent_type_access_delete
BEFORE DELETE ON project_agent_type_access
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_sessions_insert
BEFORE INSERT ON triage_chat_sessions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_sessions_update
BEFORE UPDATE ON triage_chat_sessions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_sessions_delete
BEFORE DELETE ON triage_chat_sessions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_actions_insert
BEFORE INSERT ON triage_chat_actions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_actions_update
BEFORE UPDATE ON triage_chat_actions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id) OR (p.id = NEW.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_actions_delete
BEFORE DELETE ON triage_chat_actions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id = OLD.project_id)))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_comments_insert
BEFORE INSERT ON comments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_comments_update
BEFORE UPDATE ON comments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_comments_delete
BEFORE DELETE ON comments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_labels_insert
BEFORE INSERT ON item_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_labels_update
BEFORE UPDATE ON item_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_labels_delete
BEFORE DELETE ON item_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_held_comments_insert
BEFORE INSERT ON held_comments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_held_comments_update
BEFORE UPDATE ON held_comments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_held_comments_delete
BEFORE DELETE ON held_comments
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_labels_insert
BEFORE INSERT ON item_guardrail_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_labels_update
BEFORE UPDATE ON item_guardrail_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_labels_delete
BEFORE DELETE ON item_guardrail_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_proposals_insert
BEFORE INSERT ON item_guardrail_proposals
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_proposals_update
BEFORE UPDATE ON item_guardrail_proposals
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_proposals_delete
BEFORE DELETE ON item_guardrail_proposals
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_proposal_labels_insert
BEFORE INSERT ON item_guardrail_proposal_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_proposal_labels_update
BEFORE UPDATE ON item_guardrail_proposal_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_guardrail_proposal_labels_delete
BEFORE DELETE ON item_guardrail_proposal_labels
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_embeddings_insert
BEFORE INSERT ON item_embeddings
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_embeddings_update
BEFORE UPDATE ON item_embeddings
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_embeddings_delete
BEFORE DELETE ON item_embeddings
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_mutes_insert
BEFORE INSERT ON item_mutes
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_mutes_update
BEFORE UPDATE ON item_mutes
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_mutes_delete
BEFORE DELETE ON item_mutes
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_follows_insert
BEFORE INSERT ON item_follows
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_follows_update
BEFORE UPDATE ON item_follows
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id)) OR (p.id IN (SELECT project_id FROM items WHERE id = NEW.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_item_follows_delete
BEFORE DELETE ON item_follows
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id = OLD.item_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_relations_insert
BEFORE INSERT ON relations
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id IN (NEW.item_id, NEW.related_item_id)))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_relations_update
BEFORE UPDATE ON relations
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id IN (OLD.item_id, OLD.related_item_id))) OR (p.id IN (SELECT project_id FROM items WHERE id IN (NEW.item_id, NEW.related_item_id)))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_relations_delete
BEFORE DELETE ON relations
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM items WHERE id IN (OLD.item_id, OLD.related_item_id)))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_revisions_insert
BEFORE INSERT ON wiki_revisions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM wiki_pages WHERE id = NEW.page_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_revisions_update
BEFORE UPDATE ON wiki_revisions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM wiki_pages WHERE id = OLD.page_id)) OR (p.id IN (SELECT project_id FROM wiki_pages WHERE id = NEW.page_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_wiki_revisions_delete
BEFORE DELETE ON wiki_revisions
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM wiki_pages WHERE id = OLD.page_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_messages_insert
BEFORE INSERT ON triage_chat_messages
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM triage_chat_sessions WHERE id = NEW.session_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_messages_update
BEFORE UPDATE ON triage_chat_messages
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM triage_chat_sessions WHERE id = OLD.session_id)) OR (p.id IN (SELECT project_id FROM triage_chat_sessions WHERE id = NEW.session_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_triage_chat_messages_delete
BEFORE DELETE ON triage_chat_messages
WHEN EXISTS (SELECT 1 FROM projects p WHERE p.archived_at IS NOT NULL AND ((p.id IN (SELECT project_id FROM triage_chat_sessions WHERE id = OLD.session_id))))
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

-- Restoring only the archive marker is the sole allowed project update.
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
    NEW.wiki_compile_enabled IS NOT OLD.wiki_compile_enabled
)
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;

CREATE TRIGGER archived_projects_delete
BEFORE DELETE ON projects
WHEN OLD.archived_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'archived_project_readonly');
END;
