"""#-autocomplete voor ticket-refs (BETON-254): /ref-candidates.

Substring-match op project-key + seq met ref-first ordening. Persons spec:
`#42` → alleen huidig project; `#B1` → cross-project, key bevat B én seq bevat 1.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def data(client, auth):
    for key, name in [("BETON", "Betonning"), ("BRAND", "Brandaris"), ("SOS", "SOS")]:
        client.post("/api/v1/projects", json={"key": key, "name": name}, headers=auth)
    # BETON krijgt seq 1..13 (genoeg voor substring-/prefix-ordening op cijfers).
    for i in range(1, 14):
        client.post(
            "/api/v1/projects/BETON/items",
            json={"title": f"Beton taak {i}"},
            headers=auth,
        )
    # BRAND krijgt seq 1,2; SOS seq 1.
    for i in (1, 2):
        client.post(
            "/api/v1/projects/BRAND/items", json={"title": f"Brand {i}"}, headers=auth
        )
    client.post("/api/v1/projects/SOS/items", json={"title": "Sos 1"}, headers=auth)


def _refs(client, auth, q, **params):
    qs = "&".join([f"q={q}"] + [f"{k}={v}" for k, v in params.items()])
    return [r["ref"] for r in client.get(f"/api/v1/ref-candidates?{qs}", headers=auth).json()]


def test_number_only_scoped_to_current_project(client, auth, data):
    """`#2` met project=BETON → alleen BETON-items met '2' in de seq, NIET BRAND-2."""
    refs = _refs(client, auth, "2", project="BETON")
    assert "BETON-2" in refs
    assert "BETON-12" in refs
    assert "BRAND-2" not in refs  # ander project valt buiten scope
    assert all(r.startswith("BETON-") for r in refs)


def test_number_only_exact_seq_ranked_first(client, auth, data):
    """Exacte seq staat bovenaan (`#2` → BETON-2 boven BETON-12)."""
    refs = _refs(client, auth, "2", project="BETON")
    assert refs[0] == "BETON-2"


def test_number_prefix_ordering(client, auth, data):
    """`#1` → exacte seq 1 eerst, dan seq die met 1 begint (10..13)."""
    refs = _refs(client, auth, "1", project="BETON")
    assert refs[0] == "BETON-1"
    # 10,11,12,13 bevatten allemaal '1'; komen na de exacte match.
    assert set(refs) == {"BETON-1", "BETON-10", "BETON-11", "BETON-12", "BETON-13"}


def test_letters_go_cross_project(client, auth, data):
    """`#B1` → key bevat B (BETON én BRAND) én seq bevat 1, over projecten heen."""
    refs = _refs(client, auth, "B1", project="BETON")
    assert "BRAND-1" in refs  # ander project, want letters aanwezig
    assert "BETON-1" in refs
    assert "BETON-11" in refs


def test_letters_ignore_current_project_scope(client, auth, data):
    """Zodra er letters zijn, telt het huidige project niet: `#BR` (project=BETON)
    levert BRAND-items op omdat hun key 'BR' bevat."""
    refs = _refs(client, auth, "BR", project="BETON")
    assert "BRAND-1" in refs
    assert "BRAND-2" in refs


def test_letters_only_key_substring(client, auth, data):
    """`#SOS` (alleen letters) → alle projecten met SOS in de key."""
    refs = _refs(client, auth, "SOS", project="BETON")
    assert refs == ["SOS-1"]  # alleen SOS heeft SOS in de key


def test_key_substring_case_insensitive(client, auth, data):
    """Key-match is case-insensitief (`#sos` == `#SOS`)."""
    assert _refs(client, auth, "sos", project="BETON") == ["SOS-1"]


def test_full_ref_query(client, auth, data):
    """Een volledige ref (`#BRAND-2`) splitst in letters=BRAND, digits=2."""
    refs = _refs(client, auth, "BRAND-2", project="BETON")
    assert refs == ["BRAND-2"]


def test_empty_query_returns_nothing(client, auth, data):
    assert _refs(client, auth, "", project="BETON") == []


def test_limit_caps_results(client, auth, data):
    """limit begrenst het aantal kandidaten."""
    refs = _refs(client, auth, "1", project="BETON", limit=2)
    assert len(refs) == 2
    assert refs[0] == "BETON-1"  # exacte match blijft bovenaan binnen de cap


def test_requires_auth(client, data):
    assert client.get("/api/v1/ref-candidates?q=1&project=BETON").status_code == 401


def test_requires_q(client, auth, data):
    assert client.get("/api/v1/ref-candidates?project=BETON", headers=auth).status_code == 422
