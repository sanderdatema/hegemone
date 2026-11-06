"""SSRF-adresbeleid en IP-pinning zonder echte externe verbindingen."""

import asyncio
import socket
import pytest
from betonning import webhook_targets as targets, webhooks


def test_canonical_variants_and_port_validation(monkeypatch):
    monkeypatch.delenv("BETONNING_WEBHOOK_ALLOW_LOOPBACK", raising=False)
    for host in ["127.1", "2130706433", "0x7f000001", "[::ffff:127.0.0.1]"]:
        assert webhooks.webhook_url_error("http://" + host + "/hook")
    for url in [
        "http://user:pass@receiver.example/hook",
        "http://receiver.example:bad/hook",
        "http://receiver.example:0/hook",
        "http://[bad",
    ]:
        assert webhooks.webhook_url_error(url)
    monkeypatch.setenv("BETONNING_WEBHOOK_ALLOWED_HOSTS", "receiver.example:8443")
    assert webhooks.webhook_url_error("https://receiver.example:8443/hook") is None
    assert webhooks.webhook_url_error("https://receiver.example:9443/hook") is not None


def test_resolved_addresses_are_pinned_and_all_checked(monkeypatch):
    calls = []

    def resolve(*args):
        calls.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.45.67", 8443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    url, headers, extensions = asyncio.run(
        targets.pinned_target("https://receiver.example:8443/hook")
    )
    assert str(url) == "https://10.23.45.67:8443/hook"
    assert headers["Host"] == "receiver.example:8443"
    assert headers["Connection"] == "close"
    assert extensions["sni_hostname"] == "receiver.example"
    assert len(calls) == 1
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.23.45.67", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ],
    )
    with pytest.raises(ValueError):
        asyncio.run(targets.pinned_target("http://receiver.example/hook"))
