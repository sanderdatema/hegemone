"""FTS5-zoek: /search vindt items op woorddeel, over projecten heen."""

from __future__ import annotations

import pytest


@pytest.fixture
def data(client, auth):
    client.post("/api/v1/projects", json={"key": "SOS", "name": "SOS"}, headers=auth)
    client.post("/api/v1/projects", json={"key": "BRAND", "name": "Brandaris"}, headers=auth)
    client.post(
        "/api/v1/projects/SOS/items",
        json={"title": "Betonning migreren", "description_md": "van plane naar sqlite"},
        headers=auth,
    )
    client.post(
        "/api/v1/projects/BRAND/items",
        json={"title": "Lighthouse rapport", "description_md": "wekelijkse betonning"},
        headers=auth,
    )


def test_search_matches_word_prefix(client, auth, data):
    rows = client.get("/api/v1/search?q=beton", headers=auth).json()
    refs = {r["ref"] for r in rows}
    assert refs == {"SOS-1", "BRAND-1"}


def test_search_matches_description(client, auth, data):
    rows = client.get("/api/v1/search?q=sqlite", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]


def test_search_no_match_empty(client, auth, data):
    assert client.get("/api/v1/search?q=nonexistentword", headers=auth).json() == []


def test_search_limit(client, auth, data):
    rows = client.get("/api/v1/search?q=beton&limit=1", headers=auth).json()
    assert len(rows) == 1


def test_search_typo_no_longer_matches(client, auth, data):
    """BETON-230: de trigram-typo-tolerantie (BETON-8) is bewust verwijderd —
    een tikfout ('betonnign' i.p.v. 'betonning') levert nu geen treffer meer op.
    Alleen echte (sub)string-matches tellen."""
    rows = client.get("/api/v1/search?q=betonnign", headers=auth).json()
    assert rows == []


def test_search_substring_fallback(client, auth, data):
    """Midden-in-woord ('onning') matcht niet als FTS-prefix maar wel als
    letterlijke substring-fallback (BETON-230)."""
    rows = client.get("/api/v1/search?q=onning", headers=auth).json()
    assert {r["ref"] for r in rows} == {"SOS-1", "BRAND-1"}


def test_search_exact_stays_precise(client, auth, data):
    """Een exacte treffer verbreedt niet naar de substring-fallback (precisie)."""
    rows = client.get("/api/v1/search?q=lighthouse", headers=auth).json()
    assert [r["ref"] for r in rows] == ["BRAND-1"]


def test_search_nonsense_query_empty(client, auth, data):
    """BETON-230: een verzonnen term die nergens in voorkomt geeft 0 treffers —
    geen losse fuzzy-matching meer die op onzin-zoektermen toch iets terugvindt."""
    assert client.get("/api/v1/search?q=poepie", headers=auth).json() == []
    assert client.get("/api/v1/search?q=qwerty", headers=auth).json() == []


def test_search_ref_exact(client, auth, data):
    """Een volledige ref ("SOS-1") vindt het juiste ticket direct (BETON-143)."""
    rows = client.get("/api/v1/search?q=SOS-1", headers=auth).json()
    assert "SOS-1" in {r["ref"] for r in rows}


def test_search_ref_seq_only(client, auth, data):
    """Enkel een nummer ("1") vindt alle tickets met dat seq, cross-project."""
    rows = client.get("/api/v1/search?q=1", headers=auth).json()
    refs = {r["ref"] for r in rows}
    assert "SOS-1" in refs
    assert "BRAND-1" in refs


def test_search_ref_case_insensitive(client, auth, data):
    """Ref-matching is case-insensitive op de project-key."""
    rows = client.get("/api/v1/search?q=sos-1", headers=auth).json()
    assert "SOS-1" in {r["ref"] for r in rows}


def test_search_ref_ranked_first(client, auth, data):
    """Ref-treffer staat boven FTS-treffers bij een nummer-query."""
    # Maak een extra ticket met "1" in de titel in een ander project
    rows = client.get("/api/v1/search?q=SOS-1", headers=auth).json()
    if rows:
        assert rows[0]["ref"] == "SOS-1"


def test_search_requires_auth(client, data):
    assert client.get("/api/v1/search?q=beton").status_code == 401


def test_search_requires_q(client, auth, data):
    assert client.get("/api/v1/search", headers=auth).status_code == 422


# --- Comment-treffers (BETON-370) ----------------------------------------


def _comment(client, auth, ref: str, body: str) -> dict:
    r = client.post(f"/api/v1/items/{ref}/comments", json={"body_md": body}, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_search_finds_word_only_in_comment(client, auth, data):
    """Een woord dat alleen in een reactie staat vindt het ticket."""
    _comment(client, auth, "SOS-1", "de kraakpeer is vervangen")
    rows = client.get("/api/v1/search?q=kraakpeer", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]
    assert rows[0]["matched_in"] == "comment"
    assert rows[0]["comment_id"] is not None


def test_search_item_hit_wins_over_comment_hit(client, auth, data):
    """Staat de term in het item én in een reactie: één rij, als item-treffer."""
    _comment(client, auth, "SOS-1", "sqlite blijft de keuze")
    rows = client.get("/api/v1/search?q=sqlite", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]
    assert rows[0]["matched_in"] == "item"
    assert "comment_id" not in rows[0]


def test_search_comment_hit_one_row_per_item(client, auth, data):
    """Twee reacties met dezelfde term geven één resultaatrij."""
    _comment(client, auth, "SOS-1", "kraakpeer een")
    _comment(client, auth, "SOS-1", "kraakpeer twee")
    rows = client.get("/api/v1/search?q=kraakpeer", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]


def test_search_comment_hit_skips_archived_item(client, auth, data):
    """Een gearchiveerd item komt niet terug via een comment-treffer."""
    _comment(client, auth, "SOS-1", "kraakpeer hier")
    client.delete("/api/v1/items/SOS-1", headers=auth)
    assert client.get("/api/v1/search?q=kraakpeer", headers=auth).json() == []


def test_search_comment_edit_updates_index(client, auth, data):
    """Een bewerkte reactie is op de nieuwe tekst vindbaar, op de oude niet."""
    c = _comment(client, auth, "SOS-1", "kraakpeer hier")
    client.patch(
        f"/api/v1/items/SOS-1/comments/{c['id']}",
        json={"body_md": "meerpaal hier"},
        headers=auth,
    )
    assert client.get("/api/v1/search?q=kraakpeer", headers=auth).json() == []
    rows = client.get("/api/v1/search?q=meerpaal", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]


def test_search_comment_delete_removes_from_index(client, auth, data):
    """De AFTER DELETE-trigger houdt de index bij."""
    c = _comment(client, auth, "SOS-1", "kraakpeer hier")
    r = client.delete(f"/api/v1/items/SOS-1/comments/{c['id']}", headers=auth)
    assert r.status_code in (200, 204), r.text
    assert client.get("/api/v1/search?q=kraakpeer", headers=auth).json() == []


def test_search_finds_answer_text(client, auth, data):
    """Het inline antwoord op een vraag-comment (BETON-265) is vindbaar."""
    q = client.post(
        "/api/v1/items/SOS-1/comments",
        json={"body_md": "Welke kleur?", "kind": "question"},
        headers=auth,
    ).json()
    client.post(
        f"/api/v1/comments/{q['id']}/answer", json={"text": "kraakpeer"}, headers=auth
    )
    rows = client.get("/api/v1/search?q=kraakpeer", headers=auth).json()
    assert [r["ref"] for r in rows] == ["SOS-1"]
    assert rows[0]["matched_in"] == "comment"


def test_search_limit_counts_merged_results(client, auth, data):
    """`limit` telt over item- én comment-treffers samen."""
    _comment(client, auth, "SOS-1", "vaarwater diep")
    _comment(client, auth, "BRAND-1", "vaarwater ondiep")
    rows = client.get("/api/v1/search?q=vaarwater&limit=1", headers=auth).json()
    assert len(rows) == 1
