"""Wiki-compiler: prompt-bouw, parsing, apply en de worker-flow (BETON-24)."""

from __future__ import annotations

import json

import pytest

from betonning import wiki_compiler as wc
from betonning.repo import comments as comments_repo
from betonning.repo import items as items_repo
from betonning.repo import projects as projects_repo
from betonning.repo import states as states_repo
from betonning.repo import wiki as wiki_repo


class FakeLLM:
    def __init__(self, reply: dict) -> None:
        self.reply = json.dumps(reply)
        self.last_messages = None

    def complete(self, messages):
        self.last_messages = messages
        return self.reply


class RaisingLLM:
    def complete(self, messages):
        raise RuntimeError("boom")


@pytest.fixture
def seeded(conn, seed_cast):
    """Project SOS (wiki-compile opt-in, default states) + triage-user.
    Geeft (project_id, triage_id, done_state_id)."""
    p = projects_repo.create(conn, key="SOS", name="SOS")
    projects_repo.set_wiki_compile_enabled(conn, p["id"], True)
    done = states_repo.get_by_name(conn, p["id"], "done")
    conn.commit()
    return p["id"], seed_cast["triage"]["id"], done["id"]


def _make_item(conn, project_id, title, description="", *, state_id=None):
    seq = projects_repo.next_seq(conn, project_id)
    conn.execute(
        "INSERT INTO items (project_id, seq, title, description_md, state_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, seq, title, description, state_id),
    )
    conn.commit()
    return items_repo.get_by_ref(conn, f"SOS-{seq}")


def _ref(row):
    return f"SOS-{row['seq']}"


# --- Pure delen -----------------------------------------------------------


def test_build_messages_has_ticket_comments_and_existing():
    msgs = wc.build_compile_messages(
        {"ref": "SOS-1", "title": "Deploy-fix", "state": "done", "description_md": "iets"},
        [{"author": "person", "body_md": "let op de rsync-route"}],
        "# Projectmemory\n\n## Oud\n\ntekst",
        ["oud"],
    )
    assert msgs[0]["role"] == "system"
    u = msgs[1]["content"]
    assert "SOS-1" in u and "rsync-route" in u and "oud" in u


def test_parse_compile_valid_and_fallback():
    r = wc.parse_compile('{"skip": false, "pages": [{"slug":"x","title":"X","body_md":"b"}]}')
    assert r.skip is False and r.pages[0].slug == "x"
    # Kapotte JSON → skip.
    assert wc.parse_compile("geen json").skip is True


def test_parse_compile_tolerates_control_chars_in_string():
    # Letterlijke control-char (newline) in een JSON-stringwaarde: LLM's
    # produceren dat soms ondanks instructies (BETON-179). Moet een geldige
    # parse opleveren, geen crash/exception (regressie voor BETON-318: de
    # lokale _extract_json miste strict=False en gooide hier ValueError).
    text = '{"skip": false, "pages": [{"slug":"x","title":"X","body_md":"regel1\nregel2"}]}'
    r = wc.parse_compile(text)
    assert r.skip is False
    assert r.pages[0].body_md == "regel1\nregel2"


# --- apply_compile --------------------------------------------------------


def test_apply_compile_creates_and_marks(conn, seeded):
    project_id, triage_id, done_id = seeded
    item = _make_item(conn, project_id, "Ticket", state_id=done_id)
    result = wc.CompileResult(
        skip=False,
        pages=[wc.WikiPageEdit(slug="deploy-gotchas", title="Deploy Gotchas", body_md="wees voorzichtig")],
    )
    touched = wc.apply_compile(conn, item, result, triage_id)
    assert touched == ["deploy-gotchas"]
    page = wiki_repo.get_by_slug(conn, project_id, "deploy-gotchas")
    assert page["title"] == "Deploy Gotchas" and "voorzichtig" in page["body_md"]
    # Marker gezet + event geschreven.
    assert items_repo.get(conn, item["id"])["wiki_compiled_at"] is not None
    ev = conn.execute(
        "SELECT type FROM events WHERE item_id = ? AND type = 'wiki.compiled'", (item["id"],)
    ).fetchone()
    assert ev is not None


def test_apply_compile_records_revision_authored_by_bot(conn, seeded):
    """BETON-209: een edit door de wiki-compiler-bot legt een revisie vast met de
    bot (triage) als auteur — de repo-laag registreert álle schrijfpaden."""
    project_id, triage_id, done_id = seeded
    item = _make_item(conn, project_id, "Ticket", state_id=done_id)
    result = wc.CompileResult(
        skip=False,
        pages=[wc.WikiPageEdit(slug="les", title="Les", body_md="inhoud")],
    )
    wc.apply_compile(conn, item, result, triage_id)
    page = wiki_repo.get_by_slug(conn, project_id, "les")
    revs = wiki_repo.list_revisions(conn, page["id"])
    assert len(revs) == 1
    assert revs[0]["author_handle"] == "triage"


def test_apply_compile_updates_existing_page(conn, seeded):
    project_id, triage_id, done_id = seeded
    wiki_repo.create(conn, project_id=project_id, slug="conventies", title="Conventies", body_md="oud")
    conn.commit()
    item = _make_item(conn, project_id, "T", state_id=done_id)
    result = wc.CompileResult(
        skip=False, pages=[wc.WikiPageEdit(slug="conventies", title="Conventies", body_md="nieuw")]
    )
    _, allowed = wiki_repo.compile_snapshot(conn, project_id)
    wc.apply_compile(conn, item, result, triage_id, allowed_pages=allowed)
    assert wiki_repo.get_by_slug(conn, project_id, "conventies")["body_md"] == "nieuw"
    # Geen duplicaat.
    assert len(wiki_repo.list_pages(conn, project_id)) == 1


def test_apply_compile_skip_marks_without_pages(conn, seeded):
    project_id, triage_id, done_id = seeded
    item = _make_item(conn, project_id, "Niets duurzaams", state_id=done_id)
    touched = wc.apply_compile(conn, item, wc.CompileResult(skip=True), triage_id)
    assert touched == []
    assert wiki_repo.list_pages(conn, project_id) == []
    assert items_repo.get(conn, item["id"])["wiki_compiled_at"] is not None


# --- worker ---------------------------------------------------------------


def test_find_uncompiled_respects_closed_optin_and_debounce(conn, seeded):
    project_id, _, done_id = seeded
    todo = states_repo.get_by_name(conn, project_id, "todo")
    open_item = _make_item(conn, project_id, "Open", state_id=todo["id"])
    done_item = _make_item(conn, project_id, "Klaar", state_id=done_id)
    conn.execute(
        "UPDATE items SET wiki_compiled_at = NULL, "
        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now','-600 seconds')"
    )
    conn.commit()
    found = wc.find_uncompiled(conn, debounce_seconds=60, limit=50)
    assert done_item["id"] in found and open_item["id"] not in found  # alleen closed
    # Debounce: nog niet lang genoeg stil → niets.
    assert wc.find_uncompiled(conn, debounce_seconds=3600, limit=50) == []
    # Opt-in uit → niets.
    projects_repo.set_wiki_compile_enabled(conn, project_id, False)
    conn.commit()
    assert wc.find_uncompiled(conn, debounce_seconds=60, limit=50) == []


def test_compile_once_end_to_end(conn, seeded):
    project_id, triage_id, done_id = seeded
    item = _make_item(conn, project_id, "Deploy kapot", "de rsync-route faalde", state_id=done_id)
    comments_repo.create(conn, item_id=item["id"], author_id=triage_id, body_md="oplossing: gebruik root@")
    conn.commit()
    llm = FakeLLM({
        "skip": False,
        "pages": [{"slug": "deploy", "title": "Deploy", "body_md": "Gebruik root@ voor de rsync."}],
    })
    wc.compile_once(conn, item["id"], llm, actor_id=triage_id)
    # Ticket zat in de prompt.
    assert "rsync-route" in llm.last_messages[1]["content"]
    page = wiki_repo.get_by_slug(conn, project_id, "deploy")
    assert page is not None and "root@" in page["body_md"]
    assert items_repo.get(conn, item["id"])["wiki_compiled_at"] is not None


def test_compile_once_idempotent(conn, seeded):
    project_id, triage_id, done_id = seeded
    item = _make_item(conn, project_id, "T", state_id=done_id)
    conn.execute("UPDATE items SET wiki_compiled_at = 'x' WHERE id = ?", (item["id"],))
    conn.commit()
    llm = FakeLLM({"skip": False, "pages": [{"slug": "x", "title": "X", "body_md": "b"}]})
    wc.compile_once(conn, item["id"], llm, actor_id=triage_id)
    assert wiki_repo.list_pages(conn, project_id) == []  # niet opnieuw verwerkt


def test_run_batch_continues_past_poison_and_quarantines(conn, db_path, seeded):
    """BETON-41: een falend compile-item stopt de batch niet en gaat na
    MAX_ATTEMPTS in quarantaine (de finder slaat het daarna over)."""
    project_id, triage_id, done_id = seeded
    poison = _make_item(conn, project_id, "Poison", state_id=done_id)
    conn.execute(
        "UPDATE items SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now','-600 seconds')"
    )
    conn.commit()
    llm = RaisingLLM()
    for _ in range(wc.MAX_ATTEMPTS):
        wc._run_batch(db_path, llm, triage_id, 60, 3)
    row = items_repo.get(conn, poison["id"])
    assert row["wiki_compiled_at"] is None
    assert row["wiki_compile_attempts"] == wc.MAX_ATTEMPTS
    assert row["wiki_compile_error_at"] is not None
    assert wc.find_uncompiled(conn, debounce_seconds=60, limit=50) == []  # quarantaine


@pytest.mark.parametrize("scenario", ["oversized", "indexed", "changed", "unseen"])
def test_compiler_refuses_unseen_or_changed_existing_pages(conn, seeded, scenario):
    project_id, actor, done_id = seeded
    item = _make_item(conn, project_id, "Knowledge", state_id=done_id)
    original = "keep-the-entire-body" + ("x" * 21000 if scenario == "oversized" else "")
    page = wiki_repo.create(conn, project_id=project_id, slug="lesson", title="Lesson", body_md=original)
    if scenario == "indexed":
        wiki_repo.create(conn, project_id=project_id, slug="recent", title="Recent", body_md="r" * 19000)
        wiki_repo.update(conn, page["id"], {"body_md": "o" * 2000})
        conn.execute("UPDATE wiki_pages SET updated_at='2000-01-01' WHERE id=?", (page["id"],))
        original = "o" * 2000

    class ChangingLLM(FakeLLM):
        def complete(self, messages):
            if scenario == "changed":
                wiki_repo.update(conn, page["id"], {"body_md": "concurrent knowledge"})
            return super().complete(messages)

    model = ChangingLLM({"pages": [{"slug": "lesson", "title": "Lesson", "body_md": "replacement"}]})
    if scenario == "unseen":
        result = wc.parse_compile(model.reply)
        assert wc.apply_compile(conn, item, result, actor) == []
    else:
        wc.compile_once(conn, item["id"], model, actor_id=actor)
        prompt = model.last_messages[1]["content"]
        wiki_block = prompt.split("<wiki-context>\n", 1)[1].split("\n</wiki-context>", 1)[0]
        assert len(wiki_block) <= 20000
        if scenario in ("oversized", "indexed"):
            assert original not in wiki_block
            assert "`lesson`" in wiki_block
    expected = "concurrent knowledge" if scenario == "changed" else original
    assert wiki_repo.get_by_slug(conn, project_id, "lesson")["body_md"] == expected


def test_compiler_rejects_oversized_context_instead_of_slicing():
    with pytest.raises(ValueError, match="whole-page budget"):
        wc.build_compile_messages({}, [], "x" * 20001, [])


def test_compiler_supplies_complete_selected_page(conn, seeded):
    project_id, actor, done_id = seeded
    item = _make_item(conn, project_id, "Knowledge", state_id=done_id)
    body = "start" + "x" * 18000 + "END-OF-KNOWLEDGE"
    wiki_repo.create(conn, project_id=project_id, slug="lesson", title="Lesson", body_md=body)
    model = FakeLLM({"pages": [{"slug": "lesson", "title": "Lesson", "body_md": "updated"}]})
    wc.compile_once(conn, item["id"], model, actor_id=actor)
    assert body in model.last_messages[1]["content"]
    assert wiki_repo.get_by_slug(conn, project_id, "lesson")["body_md"] == "updated"
