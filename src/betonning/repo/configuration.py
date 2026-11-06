"""Configuratieprojecties en eenmalige importpreview-opslag; pure sqlite3."""
import hashlib
import json


def agents(conn):
    return [dict(row) for row in conn.execute(
        "SELECT handle, display_name, agent_type, subscribe_all FROM users "
        "WHERE kind='agent' AND is_virtual=0 AND handle!='triage' ORDER BY handle")]


def project_access(conn, project_id):
    types = {r['agent_type']: r['level'] for r in conn.execute(
        'SELECT agent_type, level FROM project_agent_type_access WHERE project_id=? ORDER BY agent_type', (project_id,))}
    agents = {r['handle']: r['level'] for r in conn.execute(
        "SELECT u.handle, a.level FROM project_agent_access a JOIN users u ON u.id=a.user_id "
        "WHERE a.project_id=? AND u.kind='agent' AND u.is_virtual=0 AND u.handle!='triage' ORDER BY u.handle", (project_id,))}
    return types, agents


def replace_access(conn, project_id, type_defaults, agent_overrides):
    conn.execute('DELETE FROM project_agent_type_access WHERE project_id=?', (project_id,))
    # Interne/virtuele identities blijven buiten de portable regels.
    conn.execute("DELETE FROM project_agent_access WHERE project_id=? AND user_id IN "
                 "(SELECT id FROM users WHERE kind='agent' AND is_virtual=0 AND handle!='triage')", (project_id,))
    for kind, level in type_defaults.items():
        conn.execute('INSERT INTO project_agent_type_access(project_id,agent_type,level) VALUES (?,?,?)', (project_id, kind, level))
    for handle, level in agent_overrides.items():
        conn.execute('INSERT INTO project_agent_access(project_id,user_id,level) SELECT ?,id,? FROM users WHERE handle=?', (project_id, level, handle))


def baseline(conn):
    """Interne digest, nooit in export/previewrespons; geen secretwaarden loggen."""
    queries = {
        'installation': 'SELECT * FROM installation_settings ORDER BY id',
        'models': 'SELECT * FROM model_classes ORDER BY harness,class',
        'template': 'SELECT * FROM project_template ORDER BY id',
        'users': 'SELECT id,handle,display_name,kind,agent_type,active,is_virtual,subscribe_all,webhook_url,webhook_secret,api_key_hash,api_key_scopes,api_key_projects FROM users ORDER BY id',
        'projects': 'SELECT id,key,name,triage_enabled,wiki_compile_enabled,archived_at FROM projects ORDER BY id',
        'types': 'SELECT * FROM project_agent_type_access ORDER BY project_id,agent_type',
        'access': 'SELECT * FROM project_agent_access ORDER BY project_id,user_id',
    }
    rows = {name: [dict(row) for row in conn.execute(query)] for name, query in queries.items()}
    raw = json.dumps(rows, sort_keys=True, default=lambda value: value.hex()).encode()
    return hashlib.sha256(raw).hexdigest()


def save_preview(conn, token_hash, actor_id, instance_id, document, digest):
    conn.execute("DELETE FROM configuration_imports WHERE actor_id=? OR expires_at<=strftime('%Y-%m-%dT%H:%M:%fZ','now') OR consumed_at IS NOT NULL", (actor_id,))
    conn.execute("INSERT INTO configuration_imports(token_hash,actor_id,instance_id,document_json,baseline_hash,expires_at) "
                 "VALUES(?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now','+10 minutes'))",
                 (token_hash, actor_id, instance_id, json.dumps(document), digest))
    return conn.execute('SELECT expires_at FROM configuration_imports WHERE token_hash=?', (token_hash,)).fetchone()[0]


def pending_preview(conn, token_hash, actor_id, instance_id):
    row = conn.execute("SELECT * FROM configuration_imports WHERE token_hash=? AND actor_id=? AND instance_id=? "
                       "AND consumed_at IS NULL AND expires_at>strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                       (token_hash, actor_id, instance_id)).fetchone()
    return dict(row) if row else None


def consume(conn, token_hash):
    conn.execute("UPDATE configuration_imports SET consumed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE token_hash=?", (token_hash,))
