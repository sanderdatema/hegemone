"""Container-smoke met tijdelijke resources en synthetische data; geen publicatie.

Gebruik: uv run python tools/smoke_container.py --image hegemone:rc-local
Geheimen blijven uitsluitend in controllergeheugen/tijdelijke envfile. Alleen
resultaatmetadata gaat naar stdout. Alle resources hebben unieke testnamen.
"""

from __future__ import annotations

import argparse
import base64
import tarfile
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class SmokeFailure(Exception):
    """Een gecontroleerde fout zonder credential- of responsewaarden."""


def command(*args, stdin=None, stdout=None):
    result = subprocess.run(
        args, stdin=stdin, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode:
        raise SmokeFailure(f"Command failed: {args[0]} {args[1]}")
    return result.stdout.decode().strip() if stdout is None else ""


def response(client, method, path, expected=200, **kwargs):
    result = client.request(method, path, **kwargs)
    if result.status_code != expected:
        raise SmokeFailure(f"{method} {path}: HTTP {result.status_code}")
    return result.json() if result.status_code != 204 else None


async def mcp_item(base, key, ref):
    async with streamablehttp_client(
        base + "/mcp/",
        headers={"Authorization": "Bearer " + key},
        timeout=15,
        sse_read_timeout=30,
    ) as (read, write, _):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=30)
        ) as session:
            await session.initialize()
            result = await session.call_tool("get_item", {"ref": ref})
            if result.isError:
                raise SmokeFailure("MCP get_item returned an error")
            value = result.structuredContent
            if not isinstance(value, dict):
                value = json.loads(
                    next(
                        block.text for block in result.content if hasattr(block, "text")
                    )
                )
            if isinstance(value.get("result"), dict):
                value = value["result"]
            if value.get("ref") != ref or value.get("model_for_you") != {
                "class": "routine",
                "model": "fixture-model",
            }:
                raise SmokeFailure("MCP item/model mapping mismatch")


def launch(image, name, volume, env_file):
    command(
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=64m,mode=1777",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--env-file",
        str(env_file),
        "--publish",
        "127.0.0.1::8000",
        "--mount",
        "type=volume,source=" + volume + ",target=/data",
        image,
    )
    port = command("docker", "port", name, "8000/tcp").split(":")[-1]
    return "http://127.0.0.1:" + port


def wait_ready(client, name):
    for _ in range(90):
        try:
            if client.get("/health").status_code == 200:
                health = command(
                    "docker", "inspect", "--format", "{{.State.Health.Status}}", name
                )
                if health == "healthy":
                    return
        except httpx.RequestError:
            pass
        time.sleep(0.5)
    raise SmokeFailure("HTTP/Docker healthcheck did not become healthy")


def extract_archive(image, volume, archive):
    with archive.open("rb") as source:
        command(
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--read-only",
            "--user",
            "10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            "type=volume,source=" + volume + ",target=/data",
            "--entrypoint",
            "tar",
            image,
            "-C",
            "/data",
            "-xf",
            "-",
            "--no-same-owner",
            stdin=source,
        )


def legacy_fixture(directory):
    # Uitsluitend een geïsoleerde schema-51-fixture, nooit een bestaande database.
    from betonning import db
    from betonning.repo import users, projects, items, states

    data = directory / "legacy"
    data.mkdir()
    conn = db.connect(data / "hegemone.db")
    try:
        for version, sql in db._migration_files():
            if version <= 51:
                conn.executescript(sql)
        conn.execute("PRAGMA user_version=51")
        human, key = users.create(
            conn, handle="legacy-operator", display_name="Legacy operator", kind="human"
        )
        project = projects.create(conn, key="LEGACY", name="Legacy fixture")
        started = states.get_by_name(conn, project["id"], "in-progress")
        item = items.create(
            conn,
            project_id=project["id"],
            title="Preserved legacy task",
            state_id=started["id"],
            created_by=human["id"],
            plan_md="Preserved legacy plan",
        )
        identity = (human["id"], item["id"])
    finally:
        conn.close()
    archive = directory / "legacy.tar"
    with tarfile.open(archive, "w") as target:
        for path in data.iterdir():
            target.add(path, arcname=path.name)
    return archive, key, identity


def run(image):
    suffix = uuid.uuid4().hex[:12]
    name = "hegemone-smoke-" + suffix
    volume = name + "-data"
    checks = {}
    containers = [name]
    volumes = [volume]
    image = command("docker", "image", "inspect", "--format", "{{.Id}}", image)
    with tempfile.TemporaryDirectory(prefix="hegemone-container-smoke-") as directory:
        env_file = Path(directory) / "runtime.env"
        setup_token = secrets.token_urlsafe(40)
        env_file.write_text(
            "HEGEMONE_SETUP_TOKEN="
            + setup_token
            + "\nHEGEMONE_MEDIA_SECRET="
            + secrets.token_urlsafe(40)
            + "\n"
        )
        env_file.chmod(0o600)
        try:
            base = launch(image, name, volume, env_file)
            with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
                wait_ready(client, name)
                checks["health"] = True
                notices = client.get("/third-party-licenses.txt")
                inventory = response(client, "GET", "/third-party-packages.json")
                if notices.status_code != 200 or not all(
                    "Name: " + package in notices.text
                    for package in ("svelte", "@lucide/svelte", "markdown-it", "tailwindcss")
                ) or any(not package.get("license") for package in inventory):
                    raise SmokeFailure("Frontend license notices missing")
                if command("docker", "exec", name, "python", "-c",
                    "import importlib.metadata as m; "
                    "missing=[d.metadata['Name'] for d in m.distributions() "
                    "if not any(any(p.lower() in ('licenses','license','license.txt','license.md','copying','notice') "
                    "for p in f.parts) for f in (d.files or []))]; "
                    "print(len(missing))") != "0":
                    raise SmokeFailure("Python distribution license files missing")
                command("docker", "exec", name, "test", "!", "-e", "/usr/local/bin/uv")
                command("docker", "exec", name, "python", "-c",
                    "from pathlib import Path; import sysconfig; "
                    "assert (Path(sysconfig.get_path('stdlib'))/'LICENSE.txt').is_file(); "
                    "assert Path('/usr/share/doc/libc6/copyright').is_file()")
                checks["third_party_notices"] = True
                if command("docker", "exec", name, "id", "-u") != "10001":
                    raise SmokeFailure("Unexpected container UID")
                command("docker", "exec", name, "test", "-w", "/data")
                checks["non_root_volume_writable"] = True
                status = response(client, "GET", "/api/v1/setup")
                if not status["required"] or not status["enabled"]:
                    raise SmokeFailure("Fresh setup was not enabled")
                initial = response(
                    client,
                    "POST",
                    "/api/v1/setup",
                    expected=201,
                    headers={"X-Setup-Token": setup_token},
                    json={
                        "handle": "operator",
                        "display_name": "Operator",
                        "locale": "en",
                    },
                )
                admin_key = initial["api_key"]
                client.headers["Authorization"] = "Bearer " + admin_key
                response(
                    client,
                    "POST",
                    "/api/v1/onboarding/project",
                    expected=201,
                    json={"key": "SMOKE", "name": "Smoke project"},
                )
                response(client, "POST", "/api/v1/onboarding/complete")
                states = response(client, "GET", "/api/v1/projects/SMOKE/states")
                if {row["name"] for row in states} != {
                    "backlog",
                    "todo",
                    "in-progress",
                    "deferred",
                    "done",
                    "cancelled",
                }:
                    raise SmokeFailure("Default columns mismatch")
                item = response(
                    client,
                    "POST",
                    "/api/v1/projects/SMOKE/items",
                    expected=201,
                    json={"title": "Synthetic smoke task", "labels": ["routine"]},
                )
                agent = response(
                    client,
                    "POST",
                    "/api/v1/users",
                    expected=201,
                    json={
                        "handle": "builder",
                        "display_name": "Builder",
                        "kind": "agent",
                        "agent_type": "coding",
                    },
                )
                response(
                    client,
                    "PUT",
                    "/api/v1/settings/model-classes",
                    json={"mapping": {"builder": {"routine": "fixture-model"}}},
                )
                checks["setup_onboarding_defaults"] = True
                asyncio.run(mcp_item(base, agent["api_key"], item["ref"]))
                checks["authenticated_mcp_and_model_mapping"] = True
                if response(client, "GET", "/api/v1/setup")["required"]:
                    raise SmokeFailure("Setup reopened")
                response(
                    client,
                    "PATCH",
                    "/api/v1/items/" + item["ref"],
                    json={"state": "done"},
                )
                if (
                    response(client, "GET", "/api/v1/items/" + item["ref"])["state"]
                    != "done"
                ):
                    raise SmokeFailure("Ticket transition failed")
                checks["ticket_progress"] = True
                response(
                    client,
                    "POST",
                    "/api/v1/items/" + item["ref"] + "/comments",
                    expected=201,
                    json={"body_md": "Synthetic restore comment"},
                )
                response(
                    client,
                    "POST",
                    "/api/v1/projects/SMOKE/wiki",
                    expected=201,
                    json={
                        "slug": "restore-note",
                        "title": "Restore note",
                        "body_md": "Synthetic restore knowledge",
                    },
                )
                png = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="
                )
                attachment = response(
                    client,
                    "POST",
                    "/api/v1/items/" + item["ref"] + "/attachments",
                    expected=201,
                    files={"file": ("smoke.png", png, "image/png")},
                )
                provider = response(
                    client,
                    "PATCH",
                    "/api/v1/settings/installation",
                    json={
                        "schema_version": 1,
                        "expected_revision": 0,
                        "settings": {
                            "llm": {
                                "enabled": True,
                                "base_url": "http://127.0.0.1:9",
                                "model": "fixture-model",
                                "api_key": "synthetic-container-provider-key",
                            }
                        },
                    },
                )
                if not provider["runtime"]["providers"]["llm"]["ready"]:
                    raise SmokeFailure("Saved provider did not become configured")
                checks["encrypted_provider_configured"] = True
            command("docker", "stop", "--time", "15", name)
            archive = Path(directory) / "backup.tar"
            with archive.open("wb") as target:
                command(
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--user",
                    "10001",
                    "--cap-drop",
                    "ALL",
                    "--mount",
                    "type=volume,source=" + volume + ",target=/data,readonly",
                    "--entrypoint",
                    "tar",
                    image,
                    "-C",
                    "/data",
                    "-cf",
                    "-",
                    ".",
                    stdout=target,
                )
            restored = name + "-restored"
            restored_volume = volume + "-restored"
            containers.append(restored)
            volumes.append(restored_volume)
            extract_archive(image, restored_volume, archive)
            restored_base = launch(image, restored, restored_volume, env_file)
            with httpx.Client(
                base_url=restored_base,
                timeout=15,
                trust_env=False,
                headers={"Authorization": "Bearer " + admin_key},
            ) as client:
                wait_ready(client, restored)
                data = response(client, "GET", "/api/v1/items/" + item["ref"])
                if (
                    data["state"] != "done"
                    or data["comments"][0]["body_md"] != "Synthetic restore comment"
                ):
                    raise SmokeFailure("Restored ticket/comment mismatch")
                if (
                    response(client, "GET", "/api/v1/projects/SMOKE/wiki/restore-note")[
                        "body_md"
                    ]
                    != "Synthetic restore knowledge"
                ):
                    raise SmokeFailure("Restored wiki mismatch")
                if client.get(attachment["url"]).content != png:
                    raise SmokeFailure("Restored attachment mismatch")
                if response(client, "GET", "/api/v1/setup")["required"]:
                    raise SmokeFailure("Restored setup reopened")
                if response(client, "GET", "/api/v1/onboarding")["required"]:
                    raise SmokeFailure("Restored onboarding reopened")
                status = response(client, "GET", "/api/v1/settings/installation")
                if not status["runtime"]["providers"]["llm"]["ready"]:
                    raise SmokeFailure("Restored provider key did not decrypt")
                asyncio.run(mcp_item(restored_base, agent["api_key"], item["ref"]))
            checks["backup_restore_with_ownership_keys_and_content"] = True
            old_archive, old_key, identity = legacy_fixture(Path(directory))
            upgraded = name + "-upgraded"
            upgrade_volume = volume + "-upgraded"
            containers.append(upgraded)
            volumes.append(upgrade_volume)
            extract_archive(image, upgrade_volume, old_archive)
            upgraded_base = launch(image, upgraded, upgrade_volume, env_file)
            with httpx.Client(
                base_url=upgraded_base,
                timeout=15,
                trust_env=False,
                headers={"Authorization": "Bearer " + old_key},
            ) as client:
                wait_ready(client, upgraded)
                if response(client, "GET", "/api/v1/me")["id"] != identity[0]:
                    raise SmokeFailure("Upgraded identity/key mismatch")
                data = response(client, "GET", "/api/v1/items/LEGACY-1")
                if data["id"] != identity[1] or data["state"] != "in-progress":
                    raise SmokeFailure("Upgraded item mismatch")
                if (
                    response(client, "GET", "/api/v1/items/LEGACY-1/plan")["plan_md"]
                    != "Preserved legacy plan"
                ):
                    raise SmokeFailure("Upgraded plan mismatch")
                if response(client, "GET", "/api/v1/onboarding")["required"]:
                    raise SmokeFailure("Legacy user sent to onboarding")
            checks["schema_51_upgrade_preserves_identity_key_item_and_plan"] = True
            return checks
        finally:
            for container in containers:
                subprocess.run(
                    ["docker", "rm", "--force", container],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            for data_volume in volumes:
                subprocess.run(
                    ["docker", "volume", "rm", data_volume],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )


def failure_message(exc):
    """Ook SDK-exceptiongroepen tonen alleen gecontroleerde foutmetadata."""
    if isinstance(exc, SmokeFailure):
        return str(exc)
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(failure_message(child) for child in exc.exceptions)
    return type(exc).__name__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps({"ok": True, "checks": run(args.image)}))
    except Exception as exc:
        # Alleen eigen, gecontroleerde fouten kunnen tekst naar stdout sturen.
        message = failure_message(exc)
        print(json.dumps({"ok": False, "error": message}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
