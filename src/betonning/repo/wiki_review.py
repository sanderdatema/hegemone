"""Voorstellen voor beschermde kennis; alleen menselijke review activeert ze."""

from __future__ import annotations

import hashlib

from . import wiki, events


def digest(page) -> str | None:
    if page is None:
        return None
    return hashlib.sha256((page['title'] + '\0' + page['body_md']).encode()).hexdigest()


def needs_review(conn, project_id, slug, author_id):
    author = conn.execute('SELECT kind FROM users WHERE id=?', (author_id,)).fetchone()
    page = wiki.get_by_slug(conn, project_id, slug)
    return bool(author and author['kind'] != 'human' and
                (project_id is None or (page and page['protected'])))


def submit(conn, project_id, slug, title, body_md, author_id):
    page = wiki.get_by_slug(conn, project_id, slug)
    if len(title) > 300 or len(body_md) > 60000:
        raise ValueError("Kennisvoorstel overschrijdt de tekstlimiet")
    existing = conn.execute(
        "SELECT id FROM wiki_proposals WHERE project_id IS ? AND slug=? AND author_id=? AND status='pending'",
        (project_id, slug, author_id),
    ).fetchone()
    if existing:
        proposal_id = existing['id']
        conn.execute('UPDATE wiki_proposals SET title=?,body_md=?,base_updated_at=?,base_digest=? WHERE id=?',
                     (title, body_md, page['updated_at'] if page else None, digest(page), proposal_id))
    else:
        proposal_id = conn.execute(
            'INSERT INTO wiki_proposals(project_id,slug,title,body_md,author_id,base_updated_at,base_digest) VALUES(?,?,?,?,?,?,?)',
            (project_id, slug, title, body_md, author_id, page['updated_at'] if page else None, digest(page)),
        ).lastrowid
    events.record(conn, type='wiki.proposed', item_id=None, actor_id=author_id,
                  payload={'proposal_id': proposal_id, 'slug': slug})
    return {'status': 'pending', 'proposal_id': proposal_id, 'slug': slug,
            'title': title, 'body_md': body_md, 'message': 'Wacht op menselijke goedkeuring'}


def pending(conn, project_id):
    rows = conn.execute(
        "SELECT wp.*,u.handle AS author FROM wiki_proposals wp JOIN users u ON u.id=wp.author_id "
        "WHERE wp.project_id IS ? AND wp.status='pending' ORDER BY wp.id DESC LIMIT 100",
        (project_id,),
    ).fetchall()
    result = []
    for row in rows:
        page = wiki.get_by_slug(conn, project_id, row['slug'])
        result.append({**dict(row), 'current_body': page['body_md'] if page else ''})
    return result


def review(conn, proposal_id, reviewer_id, approve):
    user = conn.execute('SELECT kind FROM users WHERE id=?', (reviewer_id,)).fetchone()
    if user is None or user['kind'] != 'human':
        raise PermissionError('Alleen mensen beoordelen kennisvoorstellen')
    proposal = conn.execute("SELECT * FROM wiki_proposals WHERE id=? AND status='pending'", (proposal_id,)).fetchone()
    if proposal is None:
        raise LookupError('Onbekend of al beoordeeld voorstel')
    page = wiki.get_by_slug(conn, proposal['project_id'], proposal['slug'])
    if approve:
        if digest(page) != proposal['base_digest']:
            raise ValueError('Pagina is intussen gewijzigd; maak een nieuw voorstel')
        fields = {'title': proposal['title'], 'body_md': proposal['body_md']}
        if page:
            wiki.update(conn, page['id'], fields, author_id=reviewer_id)
        else:
            wiki.create(conn, project_id=proposal['project_id'], slug=proposal['slug'],
                        author_id=reviewer_id, **fields)
    conn.execute("UPDATE wiki_proposals SET status=?,reviewed_by=?,reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                 ('approved' if approve else 'rejected', reviewer_id, proposal_id))
    events.record(conn, type='wiki.reviewed', item_id=None, actor_id=reviewer_id,
                  payload={'proposal_id': proposal_id, 'approved': approve})
    return {'status': 'approved' if approve else 'rejected'}
