"""Out-of-band admin: host-tooling die direct op de db werkt (geen API/MCP).

De API heeft bewust geen user-CRUD, en migratie uit Plane is een eenmalige
host-operatie — beide horen hier, niet in `cli.py` (afgeschaft, BETON-133) of de
REST-API.

Gebruik:
    uv run python -m betonning.admin create-user \\
        --handle claude --name "Claude Code" --kind agent [--db betonning.db]
    uv run python -m betonning.admin rotate-key \\
        --handle claude [--db betonning.db]

    uv run python -m betonning.admin migrate-plane --from-plane [--dry-run] --db PATH

`create-user` en `rotate-key` printen de ruwe API-key één keer — bewaar hem, hij
wordt alleen als hash opgeslagen. `migrate-plane` migreert projecten/items/
comments/relaties uit Plane rechtstreeks in de db (draai op de host waar de db
staat).
"""

from __future__ import annotations

import argparse
import json

from . import db as db_module
from . import migrate as migrate_mod
from . import webhooks
from .repo import comments as comments_repo
from .repo import events as events_repo
from .repo import states as states_repo
from .repo import users as users_repo


def create_user(
    db_path: str,
    *,
    handle: str,
    display_name: str,
    kind: str = "agent",
    webhook_url: str | None = None,
    subscribe_all: bool = False,
) -> str:
    handle = users_repo.validate_handle(handle)
    conn = db_module.init_db(db_path)
    try:
        _, key = users_repo.create(
            conn,
            handle=handle,
            display_name=display_name,
            kind=kind,
            webhook_url=webhook_url,
            subscribe_all=subscribe_all,
        )
        return key
    finally:
        conn.close()


def rotate_key(db_path: str, *, handle: str) -> str | None:
    conn = db_module.init_db(db_path)
    try:
        with db_module.transaction(conn):
            rotated = users_repo.rotate_api_key(conn, handle)
        if rotated is None:
            return None
        _, key = rotated
        return key
    finally:
        conn.close()


def migrate_plane(db_path: str, *, dry_run: bool = False) -> dict:
    """Migreer uit Plane rechtstreeks in de db (out-of-band host-tool).

    Credentials uit ``~/.config/plane/projects.json``, user-mapping uit
    ``~/.config/betonning/plane-users.json``. Geeft het migration-report terug
    (per project: getelde/aangemaakte states, labels, items, comments, relaties).
    """
    plane_cfg = migrate_mod.load_plane_config()
    user_map = migrate_mod.load_user_mapping()
    plane = migrate_mod.PlaneClient(plane_cfg["base_url"], plane_cfg["api_key"])
    conn = db_module.init_db(db_path)
    try:
        report = migrate_mod.run_migration(
            conn, plane, plane_cfg["projects"], user_map, dry_run=dry_run
        )
    finally:
        conn.close()
    return report


STALE_WITHDRAW_REASON = "ticket was al afgesloten"


def withdraw_stale_questions(db_path: str, *, dry_run: bool = False) -> list[dict]:
    """Trek open vragen in op tickets die al in een completed/cancelled-state
    staan (BETON-454, eenmalige backfill). Alleen levende projecten en niet-
    gearchiveerde tickets — dezelfde set die de inbox toont. Geeft per vraag
    ``{id, ref, question}`` terug; met ``dry_run`` wordt niets geschreven."""
    conn = db_module.init_db(db_path)
    try:
        rows = conn.execute(
            f"""SELECT c.id AS id, c.item_id AS item_id, c.body_md AS body_md,
                       p.key || '-' || i.seq AS ref
                FROM comments c
                JOIN items i ON i.id = c.item_id
                JOIN projects p ON p.id = i.project_id
                JOIN states s ON s.id = i.state_id
                WHERE {comments_repo.question_open_sql('c')}
                  AND {states_repo.state_closed_sql('s')}
                  AND i.archived_at IS NULL AND p.archived_at IS NULL
                ORDER BY c.id"""
        ).fetchall()
        out = [
            {
                "id": r["id"],
                "ref": r["ref"],
                "question": ((r["body_md"] or "").strip().splitlines() or [""])[0][:80],
            }
            for r in rows
        ]
        if not dry_run:
            with db_module.transaction(conn):
                for r in rows:
                    comments_repo.mark_withdrawn(conn, r["id"], reason=STALE_WITHDRAW_REASON)
                    events_repo.record(
                        conn,
                        type="question.withdrawn",
                        item_id=r["item_id"],
                        actor_id=None,
                        payload={"comment_id": r["id"]},
                    )
        return out
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="betonning.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cu = sub.add_parser("create-user", help="Maak een user + API-key aan")
    cu.add_argument("--db", default="betonning.db")
    cu.add_argument("--handle", required=True)
    cu.add_argument("--name", required=True, dest="display_name")
    cu.add_argument("--kind", default="agent", choices=["human", "agent"])
    cu.add_argument("--webhook-url", default=None)
    cu.add_argument("--subscribe-all", action="store_true")

    rk = sub.add_parser("rotate-key", help="Roteer de API-key van een user")
    rk.add_argument("--db", default="betonning.db")
    rk.add_argument("--handle", required=True)

    st = sub.add_parser("set-telegram", help="Koppel een Telegram-chat aan een user")
    st.add_argument("--db", default="betonning.db")
    st.add_argument("--handle", required=True)
    st.add_argument("chat_id", help="Telegram chat-id (leeg → ontkoppelen)")

    sw = sub.add_parser("set-webhook", help="Zet de webhook-url van een agent")
    sw.add_argument("--db", default="betonning.db")
    sw.add_argument("handle")
    sw.add_argument("--url", required=True, help="Webhook-url (bv. Hermes-endpoint)")
    sw.add_argument("--secret", default=None, help="HMAC-secret voor de signing")

    mp = sub.add_parser(
        "migrate-plane",
        help="Migreer projecten/items/comments/relaties uit Plane in de db",
    )
    mp.add_argument("--from-plane", action="store_true", help="Bevestig: bron is Plane (enige ondersteunde bron)")
    mp.add_argument("--dry-run", action="store_true", help="Alleen tellen, niets schrijven")
    mp.add_argument("--db", default="betonning.db", help="Pad naar de Betonning-db")

    ws = sub.add_parser(
        "withdraw-stale-questions",
        help="Trek open vragen in op al afgesloten tickets (BETON-454)",
    )
    ws.add_argument("--dry-run", action="store_true", help="Alleen tonen, niets schrijven")
    ws.add_argument("--db", default="betonning.db")

    args = parser.parse_args(argv)
    if args.cmd == "create-user":
        try:
            key = create_user(
                args.db,
                handle=args.handle,
                display_name=args.display_name,
                kind=args.kind,
                webhook_url=args.webhook_url,
                subscribe_all=args.subscribe_all,
            )
        except ValueError as exc:
            print(f"Ongeldige handle '{args.handle}': {exc}")
            return 2
        print(f"User '{args.handle}' aangemaakt.")
        print(f"API-key (bewaar deze): {key}")
    elif args.cmd == "rotate-key":
        try:
            rotated_key = rotate_key(args.db, handle=args.handle)
        except users_repo.VirtualUserError:
            print(f"'{args.handle}' is een virtuele queue en krijgt geen API-key.")
            return 1
        if rotated_key is None:
            print(f"Onbekende user: {args.handle}")
            return 1
        print(f"API-key voor '{args.handle}' geroteerd.")
        print(f"Nieuwe API-key (bewaar deze): {rotated_key}")
    elif args.cmd == "set-telegram":
        chat_id = args.chat_id or None
        conn = db_module.init_db(args.db)
        try:
            ok = users_repo.set_telegram(conn, args.handle, chat_id)
        finally:
            conn.close()
        if not ok:
            print(f"Onbekende user: {args.handle}")
            return 1
        print(
            f"Telegram voor '{args.handle}' "
            + ("gekoppeld." if chat_id else "ontkoppeld.")
        )
    elif args.cmd == "set-webhook":
        # Zelfde poort als de API-route (BETON-378): loopback/link-local en een
        # eventuele allowlist gelden ook out-of-band.
        reason = webhooks.webhook_url_error(args.url)
        if reason is not None:
            print(reason)
            return 1
        conn = db_module.init_db(args.db)
        try:
            ok = users_repo.set_webhook(conn, args.handle, args.url, args.secret)
        finally:
            conn.close()
        if not ok:
            print(f"Onbekende user: {args.handle}")
            return 1
        print(f"Webhook voor '{args.handle}' gezet: {args.url}")
    elif args.cmd == "migrate-plane":
        if not args.from_plane:
            print("Gebruik --from-plane (enige ondersteunde bron).", flush=True)
            return 1
        report = migrate_plane(args.db, dry_run=args.dry_run)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.cmd == "withdraw-stale-questions":
        found = withdraw_stale_questions(args.db, dry_run=args.dry_run)
        for q in found:
            print(f"{q['ref']}  comment {q['id']}  {q['question']}")
        verb = "zou intrekken" if args.dry_run else "ingetrokken"
        print(f"{len(found)} vragen {verb}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
