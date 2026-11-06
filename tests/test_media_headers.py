"""Filename-sanitatie voor Content-Disposition (BETON-380)."""

from __future__ import annotations

from betonning.media_headers import media_headers, safe_filename


def test_safe_filename_keeps_ordinary_names():
    assert safe_filename("plaatje.png") == "plaatje.png"
    assert safe_filename("mijn-foto_2.jpeg") == "mijn-foto_2.jpeg"


def test_safe_filename_strips_quotes_semicolons_and_paths():
    assert '"' not in safe_filename('ra"re.png')
    assert ";" not in safe_filename("a;b.png")
    assert "/" not in safe_filename("../../etc/passwd")


def test_safe_filename_caps_length_and_falls_back():
    assert len(safe_filename("a" * 500)) == 100
    assert safe_filename("") == "bestand"
    assert safe_filename(None) == "bestand"
    assert safe_filename("///") == "bestand"


def test_media_headers_immutable_flag_switches_the_cache_directive():
    assert "immutable" in media_headers("x.png", immutable=True)["Cache-Control"]
    assert "immutable" not in media_headers("x.png", immutable=False)["Cache-Control"]
    for immutable in (True, False):
        headers = media_headers("x.png", immutable=immutable)
        assert headers["Cache-Control"].startswith("private")
        assert headers["X-Content-Type-Options"] == "nosniff"


# --- Niet-Latijnse namen (BETON-395) ---------------------------------------


def test_safe_filename_never_returns_a_nameless_dotfile():
    """Een volledig niet-Latijnse stam mag geen kale extensie opleveren."""
    assert safe_filename("日誌.log") == "bestand.log"
    assert safe_filename("日誌") == "bestand"
    assert not safe_filename("日誌.log").startswith(".")


def test_media_headers_adds_rfc5987_filename_star_for_non_ascii():
    headers = media_headers("日誌.log", immutable=False, disposition="attachment")
    disposition = headers["Content-Disposition"]
    # ASCII-terugval blijft bruikbaar (geen kaal dotfile) én blijft aanwezig
    # voor clients die filename* niet begrijpen.
    assert disposition.startswith('attachment; filename="bestand.log"')
    assert "filename*=UTF-8''%E6%97%A5%E8%AA%8C.log" in disposition


def test_media_headers_skips_filename_star_for_plain_ascii_names():
    """Geen tweede directive als de ASCII-terugval de naam al volledig dekt —
    anders breekt een bestaand contract (BETON-380) dat op één filename=
    rekent."""
    headers = media_headers("server.log", immutable=False, disposition="attachment")
    assert headers["Content-Disposition"] == 'attachment; filename="server.log"'
    assert "filename*" not in headers["Content-Disposition"]


def test_media_headers_non_ascii_filename_star_has_no_crlf_or_quotes():
    """filename* percent-encodeert alles buiten het onreserved-alfabet, dus
    ook CR/LF/aanhalingstekens in een niet-ASCII naam ontsnappen niet."""
    headers = media_headers('日誌"\r\n.log', immutable=False)
    disposition = headers["Content-Disposition"]
    star = disposition.split("filename*=UTF-8''", 1)[1]
    assert "\r" not in star
    assert "\n" not in star
    assert '"' not in star
