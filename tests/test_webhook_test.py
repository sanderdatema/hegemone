"""Testdelivery door de echte dispatcher met uitsluitend fake transport/DNS."""

import asyncio
import json
import socket
from datetime import datetime, timezone, timedelta

import httpx
import pytest

from betonning import server, webhooks, webhook_targets
from betonning.repo import users

SECRET = "synthetic-signing-secret-for-webhook-tests"
BASE = "/api/v1/users/receiver/webhook-test"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(server, "load_dotenv", lambda: None)
    monkeypatch.setenv("HEGEMONE_WEBHOOK_ALLOW_LOOPBACK", "0")
    monkeypatch.setenv("HEGEMONE_WEBHOOK_ALLOWED_HOSTS", "")
    monkeypatch.setenv(
        "HEGEMONE_MEDIA_SECRET", "synthetic-test-media-material-000000000000000"
    )
    monkeypatch.setattr(
        webhook_targets.socket,
        "getaddrinfo",
        lambda host, port, *args: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", port))
        ],
    )


@pytest.fixture
def receiver(conn):
    user, _ = users.create(
        conn,
        handle="receiver",
        display_name="Receiver",
        kind="agent",
        agent_type="hermes",
        webhook_url="https://receiver.example/events",
        webhook_secret=SECRET,
    )
    return user


def deliver(conn, handler, **kwargs):
    async def go():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            timeout=webhooks.DELIVERY_TIMEOUT,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            return await webhooks.deliver_pending(conn, client, **kwargs)

    return asyncio.run(go())


def test_only_target_receives_synthetic_signed_pinned_payload(
    client, auth, conn, receiver, project
):
    users.create(
        conn,
        handle="other",
        display_name="Other",
        kind="agent",
        webhook_url="https://other.example/events",
        subscribe_all=True,
    )
    client.post(
        f"/api/v1/projects/{project}/items",
        headers=auth,
        json={
            "title": "PRIVATE-TICKET-CONTENT",
            "description_md": "PRIVATE-TICKET-CONTENT",
        },
    )
    conn.execute("DELETE FROM webhook_deliveries")
    response = client.post(BASE, headers=auth)
    assert response.status_code == 202 and response.json()["status"] == "pending"
    delivery_id = response.json()["id"]
    assert client.post(BASE, headers=auth).json()["id"] == delivery_id
    assert conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == 1
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"secret": SECRET})

    assert deliver(conn, handler) == 1 and len(requests) == 1
    request = requests[0]
    body = request.content
    payload = json.loads(body)
    assert (
        request.url.host == "203.0.113.10"
        and request.headers["host"] == "receiver.example"
    )
    assert request.extensions["sni_hostname"] == "receiver.example"
    assert request.headers["x-betonning-signature"] == webhooks.sign(SECRET, body)
    assert request.headers["x-webhook-signature-v2"] == webhooks.sign_v2(
        SECRET, request.headers["x-webhook-timestamp"], body
    )
    assert payload["test"] and payload["expected_action"] == "stand_down"
    assert payload["item"] is None and payload["wiki"] is None
    assert "PRIVATE-TICKET-CONTENT" not in body.decode() and SECRET not in body.decode()
    status = client.get(BASE + "/" + str(delivery_id), headers=auth)
    assert status.json()["status"] == "delivered" and SECRET not in status.text
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM webhook_deliveries WHERE channel='telegram'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    "change",
    [
        {"active": False},
        {"webhook_url": None},
        {"webhook_url": "https://different.example/events"},
        {"webhook_secret": "different-synthetic-secret"},
    ],
)
def test_changed_target_is_cancelled_without_a_call(
    client, auth, conn, receiver, change
):
    delivery_id = client.post(BASE, headers=auth).json()["id"]
    users.admin_update(conn, receiver["id"], change)
    requests = []
    deliver(conn, lambda request: requests.append(request) or httpx.Response(200))
    assert requests == []
    assert (
        client.get(BASE + "/" + str(delivery_id), headers=auth).json()["status"]
        == "cancelled"
    )


def test_failure_retries_and_redacts_exception_in_status_and_logs(
    client, auth, conn, receiver, caplog
):
    delivery_id = client.post(BASE, headers=auth).json()["id"]

    def handler(request):
        raise httpx.ConnectError(
            SECRET + " https://example.test/private-capability", request=request
        )

    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    deliver(conn, handler, now=now, max_attempts=2)
    result = client.get(BASE + "/" + str(delivery_id), headers=auth).json()
    assert (
        result["status"] == "pending"
        and result["attempts"] == 1
        and result["next_retry_at"]
    )
    deliver(conn, handler, now=now + timedelta(seconds=10), max_attempts=2)
    result = client.get(BASE + "/" + str(delivery_id), headers=auth)
    assert result.json()["status"] == "failed"
    assert SECRET not in result.text and SECRET not in caplog.text
    error = conn.execute(
        "SELECT last_error FROM webhook_deliveries WHERE id=?", (delivery_id,)
    ).fetchone()[0]
    assert (
        "ConnectError" in error
        and SECRET not in error
        and "private-capability" not in error
    )


def test_forbidden_target_inactive_and_agent_or_unscoped_requests_are_rejected(
    client, auth, conn, receiver
):
    user, key = users.create(
        conn, handle="requester", display_name="Agent", kind="agent"
    )
    assert (
        client.post(BASE, headers={"Authorization": f"Bearer {key}"}).status_code == 403
    )
    users.admin_update(
        conn, user["id"], {"kind": "human", "api_key_scopes": ["read", "write"]}
    )
    assert (
        client.post(BASE, headers={"Authorization": f"Bearer {key}"}).status_code == 403
    )
    users.admin_update(conn, receiver["id"], {"active": False})
    assert client.post(BASE, headers=auth).status_code == 409
    users.admin_update(
        conn, receiver["id"], {"active": True, "webhook_url": "http://127.0.0.1/events"}
    )
    assert client.post(BASE, headers=auth).status_code == 422
    assert conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == 0


def test_redirect_is_not_followed_and_status_reports_only_http_code(
    client, auth, conn, receiver
):
    delivery_id = client.post(BASE, headers=auth).json()["id"]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            302, headers={"location": "https://different.example/" + SECRET}
        )

    deliver(conn, handler, max_attempts=1)
    assert len(requests) == 1
    result = client.get(BASE + "/" + str(delivery_id), headers=auth)
    assert result.json()["status"] == "failed" and result.json()["http_status"] == 302
    assert SECRET not in result.text


def test_csrf_and_request_rate_limit(client, auth, conn, receiver):
    session = client.post("/api/v1/session", headers=auth).json()
    assert client.post(BASE).status_code == 403

    class Limited:
        def check(self, *args, **kwargs):
            return 5

    client.app.state.webhook_test_limiter = Limited()
    response = client.post(BASE, headers={"X-CSRF-Token": session["csrf_token"]})
    assert response.status_code == 429 and response.headers["retry-after"] == "5"
    assert conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == 0


def test_dns_rebinding_is_blocked_before_transport(
    client, auth, conn, receiver, monkeypatch
):
    delivery_id = client.post(BASE, headers=auth).json()["id"]
    monkeypatch.setattr(
        webhook_targets.socket,
        "getaddrinfo",
        lambda host, port, *args: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
        ],
    )
    calls = []
    deliver(
        conn,
        lambda request: calls.append(request) or httpx.Response(200),
        max_attempts=1,
    )
    assert calls == []
    assert (
        client.get(BASE + "/" + str(delivery_id), headers=auth).json()["status"]
        == "failed"
    )
