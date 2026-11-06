"""Native applicatiereleases voorbereiden/activeren; geen infrastructuurbeheer."""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen


def validate_profile(profile):
    required = {"host", "root", "data_dir", "service", "user", "python", "health_url"}
    if not required <= profile.keys() or profile.keys() - required - {"config_paths"}:
        raise ValueError("Ongeldige deploymentprofielvelden")
    if not re.fullmatch(
        r"(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.-]*", profile["host"]
    ):
        raise ValueError("Ongeldige SSH-host")
    for field in ("root", "data_dir", "python"):
        value = profile[field]
        if not re.fullmatch(r"/[a-zA-Z0-9_./-]+", value) or ".." in Path(value).parts:
            raise ValueError("Ongeldig pad in deploymentprofiel")
        if len(Path(value).parts) < 3:
            raise ValueError("Deploymentpad is te breed")
    root, data = Path(profile["root"]), Path(profile["data_dir"])
    if data == Path("/var/lib") or any(
        path.is_relative_to(base)
        for path in (root, data)
        for base in (
            Path("/etc"),
            Path("/usr"),
            Path("/proc"),
            Path("/dev"),
            Path("/sys"),
        )
    ):
        raise ValueError("Deploymentpad is geen applicatiedirectory")
    if root.is_relative_to(data) or data.is_relative_to(root):
        raise ValueError("Code en data moeten afzonderlijk staan")
    for field in ("service", "user"):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]*", profile[field]):
            raise ValueError("Ongeldige service/user")
    if profile["user"] == "root":
        raise ValueError("De applicatie mag niet als root draaien")
    url = urlsplit(profile["health_url"])
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != "/health"
    ):
        raise ValueError("Healthcheck moet de lokale applicatie gebruiken")
    for value in profile.get("config_paths", []):
        if (
            not re.fullmatch(r"/[a-zA-Z0-9_./-]+", value)
            or ".." in Path(value).parts
            or len(Path(value).parts) < 3
        ):
            raise ValueError("Ongeldig configuratiebackuppad")
    return profile


def call(*args, cwd=None, output=None, env=None):
    result = subprocess.run(
        args,
        cwd=cwd,
        stdout=output or subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    if result.returncode:
        raise RuntimeError("Applicatiecommando mislukt: " + args[0])
    return result.stdout.decode().strip() if output is None else ""


def safe_extract(archive, destination):
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or ".git" in path.parts
                or path.name == ".env"
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Onveilig release-archief")
        bundle.extractall(destination, filter="data")


def prepare(profile, revision, digest):
    root = Path(profile["root"])
    archive = root / "staging" / (digest + ".tar")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise ValueError("Releasehash komt niet overeen")
    release = root / "releases" / (revision + "-" + digest[:12])
    marker = release / ".hegemone-release.json"
    if marker.exists():
        if json.loads(marker.read_text()) != {"commit": revision, "sha256": digest}:
            raise ValueError("Bestaande release wijkt af")
        return release
    if release.exists():
        raise ValueError("Onvolledige release; inspecteer vóór opnieuw voorbereiden")
    release.mkdir(parents=True, mode=0o755)
    safe_extract(archive, release)
    log = root / "operations" / ("prepare-" + revision + ".log")
    with log.open("w") as output:
        log.chmod(0o600)
        call(
            "uv",
            "--no-cache",
            "sync",
            "--locked",
            "--no-dev",
            "--extra",
            "mcp",
            "--python",
            profile["python"],
            "--python-preference",
            "only-system",
            cwd=release,
            output=output,
            env={**os.environ, "UV_PYTHON_DOWNLOADS": "never"},
        )
    if (release / ".venv/bin/python").resolve() != Path(profile["python"]).resolve():
        raise ValueError("Venv gebruikt niet de opgegeven systeem-Python")
    for directory, _, files in os.walk(release):
        Path(directory).chmod(Path(directory).stat().st_mode | 0o055)
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                mode = path.stat().st_mode
                path.chmod(mode | 0o044 | (0o011 if mode & 0o100 else 0))
    marker.write_text(json.dumps({"commit": revision, "sha256": digest}) + "\n")
    return release


def switch_link(current, target):
    temporary = current.with_name("current.next")
    if temporary.exists() or temporary.is_symlink():
        raise ValueError("Onverwachte tijdelijke releaselink")
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(current)


def data_size(data):
    return sum(
        path.stat().st_size
        for child in data.iterdir()
        if child.name != "backups"
        for path in ([child] if child.is_file() else child.rglob("*"))
        if path.is_file() and not path.is_symlink()
    )


def backup(profile, release_id):
    data = Path(profile["data_dir"])
    destination = (
        data
        / "backups"
        / (
            "pre-hegemone-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + release_id[:12]
            + ".tar.gz"
        )
    )
    if not destination.parent.exists():
        destination.parent.mkdir(mode=0o750)
        identity = data.stat()
        os.chown(destination.parent, identity.st_uid, identity.st_gid)
    with destination.open("xb") as output:
        destination.chmod(0o600)
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            for child in data.iterdir():
                if child.name != "backups":
                    bundle.add(child, arcname="data/" + child.name)
            for name in profile.get("config_paths", []):
                path = Path(name)
                if path.exists():
                    bundle.add(path, arcname="config/" + str(path).lstrip("/"))
    with tarfile.open(destination) as bundle:
        if not any(
            member.name.startswith("data/") and member.isfile()
            for member in bundle.getmembers()
        ):
            raise ValueError("Databackup is leeg")
    return destination


def healthy(url):
    try:
        with urlopen(url, timeout=3) as response:
            if json.load(response).get("status") != "ok":
                return False
        with urlopen(url.removesuffix("health"), timeout=3) as response:
            return b"<title>Hegemone</title>" in response.read()
    except Exception:
        return False


def activate(profile, release):
    root, data = Path(profile["root"]), Path(profile["data_dir"])
    current = root / "current"
    if not current.is_symlink() or not current.exists():
        raise ValueError("Configureer eerst de bestaande service en current-link")
    previous = current.resolve()
    if call(
        "systemctl", "show", profile["service"], "-p", "WorkingDirectory", "--value"
    ) != str(current):
        raise ValueError("Service wijst niet naar de Hegemone-current-link")
    if (
        call("systemctl", "show", profile["service"], "-p", "User", "--value")
        != profile["user"]
    ):
        raise ValueError("Onverwachte applicatiegebruiker")
    if shutil.disk_usage(data).free < data_size(data) + 64 * 1024 * 1024:
        raise ValueError("Te weinig vrije ruimte voor consistente backup")
    call("systemctl", "stop", profile["service"])
    try:
        saved = backup(profile, release.name)
        switch_link(current, release)
        call("systemctl", "start", profile["service"])
        for _ in range(30):
            if healthy(profile["health_url"]):
                return {
                    "state": "active",
                    "release": str(release),
                    "previous": str(previous),
                    "backup": str(saved),
                }
            time.sleep(1)
        raise RuntimeError("Nieuwe applicatie werd niet healthy")
    except Exception:
        switch_link(current, previous)
        call("systemctl", "restart", profile["service"])
        raise RuntimeError(
            "Activatie mislukt; vorige bron hersteld, data niet teruggezet"
        ) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40,64}", args.revision) or not re.fullmatch(
        r"[a-f0-9]{64}", args.digest
    ):
        raise ValueError("Ongeldige release-identiteit")
    profile = validate_profile(json.loads(base64.b64decode(args.config)))
    release = prepare(profile, args.revision, args.digest)
    result = (
        activate(profile, release)
        if args.activate
        else {"state": "prepared", "release": str(release)}
    )
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc)) from None
