"""Migratie uit Plane → Betonning.

`run_migration` is puur mapping-logica: het krijgt een `plane`-object met de
data-methodes (states/labels/issues/comments/relations) en schrijft naar de
Betonning-db via de repo-laag. `PlaneClient` is de echte HTTP-implementatie;
tests injecteren een fake. Zo is de mapping los van het netwerk testbaar.

Idempotent: items worden op `plane_id` overgeslagen als ze al bestaan.
Sequence-nummers blijven behouden (SOS-123 → SOS-123). `--dry-run` telt alleen.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Protocol

import httpx

from .repo import comments as comments_repo
from .repo import items as items_repo
from .repo import labels as labels_repo
from .repo import projects as projects_repo
from .repo import relations as relations_repo
from .repo import states as states_repo
from .repo import users as users_repo

PLANE_CONFIG = "~/.config/plane/projects.json"
USER_MAP_CONFIG = "~/.config/betonning/plane-users.json"

# Plane relation_type → (canoniek opslag-type, omgekeerd t.o.v. bron-issue).
RELATION_MAP = {
    "blocking": ("blocks", False),
    "blocked_by": ("blocks", True),
    "duplicate": ("duplicate_of", False),
    "relates_to": ("relates_to", False),
}


class Plane(Protocol):
    def states(self, workspace: str, project_id: str) -> list[dict]: ...
    def labels(self, workspace: str, project_id: str) -> list[dict]: ...
    def issues(self, workspace: str, project_id: str) -> list[dict]: ...
    def comments(self, workspace: str, project_id: str, issue_id: str) -> list[dict]: ...
    def relations(self, workspace: str, project_id: str, issue_id: str) -> list[dict]: ...


# --- Config-loaders -------------------------------------------------------


def load_plane_config(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("PLANE_CONFIG", PLANE_CONFIG)).expanduser()
    return json.loads(p.read_text(encoding="utf-8"))


def load_user_mapping(path: str | None = None) -> dict:
    p = Path(path or os.environ.get("BETONNING_USER_MAP", USER_MAP_CONFIG)).expanduser()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# --- Echte Plane-client ---------------------------------------------------


class PlaneClient:
    """Plane API v1. Paginatie via cursor (zoals scripts/plane.py)."""

    # Bij 429 (Plane-rate-limit) opnieuw proberen: honoreer Retry-After,
    # anders exponentiële backoff. Een volledige migratie doet duizenden calls.
    MAX_RETRIES = 6

    def __init__(self, base_url: str, api_key: str):
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=30.0,
        )

    def _proj(self, ws: str, pid: str) -> str:
        return f"{self._base}/api/v1/workspaces/{ws}/projects/{pid}"

    def _get(self, url: str) -> dict:
        for attempt in range(self.MAX_RETRIES + 1):
            resp = self._client.get(url)
            if resp.status_code == 429 and attempt < self.MAX_RETRIES:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2.0**attempt
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        # Onbereikbaar: laatste poging heeft geretourneerd of geraised.
        raise RuntimeError("unreachable")

    def _paginated(self, url: str) -> list[dict]:
        out: list[dict] = []
        cursor = None
        while True:
            page = self._get(url + (f"&cursor={cursor}" if cursor else ""))
            results = page.get("results", page if isinstance(page, list) else [])
            out.extend(results)
            nxt = page.get("next_cursor") if isinstance(page, dict) else None
            if not nxt or nxt == cursor or not results:
                break
            cursor = nxt
        return out

    def states(self, ws: str, pid: str) -> list[dict]:
        return self._paginated(f"{self._proj(ws, pid)}/states/?per_page=100")

    def labels(self, ws: str, pid: str) -> list[dict]:
        return self._paginated(f"{self._proj(ws, pid)}/labels/?per_page=100")

    def issues(self, ws: str, pid: str) -> list[dict]:
        return self._paginated(f"{self._proj(ws, pid)}/issues/?per_page=100")

    def comments(self, ws: str, pid: str, issue_id: str) -> list[dict]:
        return self._paginated(
            f"{self._proj(ws, pid)}/issues/{issue_id}/comments/?per_page=100"
        )

    def relations(self, ws: str, pid: str, issue_id: str) -> list[dict]:
        try:
            data = self._get(f"{self._proj(ws, pid)}/issues/{issue_id}/relations/")
        except httpx.HTTPError:
            return []
        return _normalize_relations(data)


def _normalize_relations(data) -> list[dict]:
    """Plane's relatie-payload → [{relation_type, related_issue}]."""
    out: list[dict] = []
    # Vorm A: {"blocking": [...], "blocked_by": [...], ...}. Entries zijn ofwel
    # kale UUID-strings (echte Plane-vorm) ofwel dicts met een issue-veld.
    if isinstance(data, dict) and any(k in data for k in RELATION_MAP):
        for rtype, entries in data.items():
            if rtype not in RELATION_MAP:
                continue
            for e in entries or []:
                if isinstance(e, str):
                    rel = e
                else:
                    rel = e.get("issue") or e.get("related_issue") or e.get("id")
                if rel:
                    out.append({"relation_type": rtype, "related_issue": rel})
        return out
    # Vorm B: platte lijst met relation_type + related_issue.
    for e in data if isinstance(data, list) else data.get("results", []):
        rtype = e.get("relation_type")
        rel = e.get("related_issue") or e.get("issue")
        if rtype and rel:
            out.append({"relation_type": rtype, "related_issue": rel})
    return out


# --- Mapping-logica -------------------------------------------------------


def _text(issue: dict) -> str:
    return issue.get("description_stripped") or issue.get("description_html") or ""


def run_migration(
    conn: sqlite3.Connection,
    plane: Plane,
    projects_config: dict,
    user_map: dict,
    *,
    dry_run: bool = False,
) -> dict:
    """Migreer alle projecten uit `projects_config`. Geeft een telrapport terug."""
    report: dict = {"dry_run": dry_run, "projects": {}}

    def uid_for(plane_uuid: str | None) -> int | None:
        handle = user_map.get(plane_uuid) if plane_uuid else None
        if not handle:
            return None
        user = users_repo.get_by_handle(conn, handle)
        return user["id"] if user else None

    for key, pcfg in projects_config.items():
        ws, pid = pcfg["workspace"], pcfg["project_id"]
        counts = {
            "states": 0,
            "labels": 0,
            "items_created": 0,
            "items_skipped": 0,
            "comments": 0,
            "relations": 0,
        }

        project = projects_repo.get_by_key(conn, key)
        if project is None and not dry_run:
            projects_repo.create(
                conn, key=key, name=pcfg.get("name", key), with_default_states=False
            )
            project = projects_repo.get_by_key(conn, key)
        project_id = project["id"] if project else None

        # States
        plane_states = plane.states(ws, pid)
        state_name_by_uuid = {s["id"]: s["name"] for s in plane_states}
        for s in plane_states:
            if dry_run or project_id is None:
                counts["states"] += 1
                continue
            if states_repo.get_by_name(conn, project_id, s["name"]) is None:
                states_repo.create(
                    conn,
                    project_id=project_id,
                    name=s["name"],
                    group=s.get("group", "backlog"),
                    color=s.get("color", "#95a5a6"),
                )
                counts["states"] += 1

        # Labels
        plane_labels = plane.labels(ws, pid)
        label_name_by_uuid = {label_entry["id"]: label_entry["name"] for label_entry in plane_labels}
        for label_entry in plane_labels:
            if dry_run or project_id is None:
                counts["labels"] += 1
                continue
            if labels_repo.get_by_name(conn, project_id, label_entry["name"]) is None:
                labels_repo.create(
                    conn,
                    project_id=project_id,
                    name=label_entry["name"],
                    color=label_entry.get("color", "#95a5a6"),
                )
                counts["labels"] += 1

        # Issues → items (behoud seq + plane_id)
        issues = plane.issues(ws, pid)
        plane_to_item: dict[str, int] = {}
        for iss in issues:
            existing = (
                items_repo.get_by_plane_id(conn, iss["id"]) if project_id else None
            )
            if existing is not None:
                counts["items_skipped"] += 1
                plane_to_item[iss["id"]] = existing["id"]
                continue
            counts["items_created"] += 1
            if dry_run or project_id is None:
                continue

            state_name = state_name_by_uuid.get(iss.get("state"))
            state = (
                states_repo.get_by_name(conn, project_id, state_name)
                if state_name
                else None
            )
            assignees = iss.get("assignees") or []
            assignee_id = uid_for(assignees[0]) if assignees else None
            row = items_repo.create(
                conn,
                project_id=project_id,
                title=iss.get("name", "(zonder titel)"),
                description_md=_text(iss),
                state_id=state["id"] if state else None,
                priority=iss.get("priority") or "none",
                assignee_id=assignee_id,
                created_by=uid_for(iss.get("created_by")) or assignee_id,
                plane_id=iss["id"],
                seq=iss["sequence_id"],
            )
            plane_to_item[iss["id"]] = row["id"]

            # Timestamps behouden (repo zet standaard 'now').
            conn.execute(
                "UPDATE items SET created_at = COALESCE(?, created_at), "
                "updated_at = COALESCE(?, updated_at), completed_at = ? WHERE id = ?",
                (iss.get("created_at"), iss.get("updated_at"), iss.get("completed_at"), row["id"]),
            )

            # Labels koppelen
            label_names = [
                label_name_by_uuid.get(lid)
                for lid in (iss.get("label_ids") or iss.get("labels") or [])
            ]
            label_ids = [
                label["id"]
                for n in label_names
                if n and (label := labels_repo.get_by_name(conn, project_id, n)) is not None
            ]
            if label_ids:
                labels_repo.set_for_item(conn, row["id"], label_ids)

        # Parents (tweede pass: alle items bestaan nu)
        if not dry_run and project_id is not None:
            for iss in issues:
                parent_uuid = iss.get("parent")
                if not parent_uuid:
                    continue
                child = plane_to_item.get(iss["id"])
                parent = plane_to_item.get(parent_uuid)
                if parent is None:
                    prow = items_repo.get_by_plane_id(conn, parent_uuid)
                    parent = prow["id"] if prow else None
                if child and parent:
                    conn.execute(
                        "UPDATE items SET parent_id = ? WHERE id = ?", (parent, child)
                    )

            # next_seq = max(seq) + 1
            if issues:
                maxseq = max(i["sequence_id"] for i in issues)
                conn.execute(
                    "UPDATE projects SET next_seq = ? WHERE id = ?",
                    (maxseq + 1, project_id),
                )

        # Comments
        for iss in issues:
            cs = plane.comments(ws, pid, iss["id"])
            counts["comments"] += len(cs)
            if dry_run or project_id is None:
                continue
            item_id = plane_to_item.get(iss["id"])
            if item_id is None:
                continue
            for c in cs:
                body = c.get("comment_stripped") or c.get("comment_html") or ""
                row = comments_repo.create(
                    conn,
                    item_id=item_id,
                    author_id=uid_for(c.get("actor")),
                    body_md=body,
                )
                if c.get("created_at"):
                    conn.execute(
                        "UPDATE comments SET created_at = ?, updated_at = ? WHERE id = ?",
                        (c["created_at"], c.get("updated_at", c["created_at"]), row["id"]),
                    )

        # Relaties (gericht opgeslagen)
        for iss in issues:
            rels = plane.relations(ws, pid, iss["id"])
            counts["relations"] += len(rels)
            if dry_run or project_id is None:
                continue
            src = plane_to_item.get(iss["id"])
            if src is None:
                continue
            for r in rels:
                mapping = RELATION_MAP.get(r["relation_type"])
                if mapping is None:
                    continue
                stored_type, reversed_ = mapping
                target = plane_to_item.get(r["related_issue"])
                if target is None:
                    trow = items_repo.get_by_plane_id(conn, r["related_issue"])
                    target = trow["id"] if trow else None
                if target is None:
                    continue
                a, b = (target, src) if reversed_ else (src, target)
                relations_repo.create(
                    conn, item_id=a, related_item_id=b, stored_type=stored_type
                )

        report["projects"][key] = counts

    return report
