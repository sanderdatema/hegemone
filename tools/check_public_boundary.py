"""Controleer publieke bron en committeksten zonder gevonden privé-inhoud te tonen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlsplit

LEGAL_NOTICES = {
    "LICENSE",
    "FRONTEND_LICENSES.txt",
    "docs/hegemone/LICENSE",
    "docs/hegemone/FRONTEND_LICENSES.txt",
}
FIXTURE_ADDRESSES = {
    ".".join(map(str, parts)) for parts in [(10, 23, 45, 67), (10, 0, 0, 5)]
}
PERSONAL_PATH = re.compile(r"/(?:Users|home|root)/[A-Za-z0-9_.-]+")
LAN = re.compile(
    r"(?<![0-9.])(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![0-9.])"
)
INTERNAL_TICKET = re.compile(r"\bBETON-\d+\b")
SUBJECT = re.compile(
    r"^(?:feat|fix|docs|refactor|test|build|ci|perf|chore|revert|merge)(?:\([a-zA-Z0-9_-]+\))?!?: \S.+$"
)
CONVERSATION = re.compile(
    r"\b(?:zoals besproken|zoals je vroeg|de gebruiker vroeg|as you asked|as discussed in (?:our |the )?chat)\b",
    re.I,
)


def settings(root):
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    names = [entry["name"] for entry in project.get("authors", [])]
    return names, project["urls"]["Repository"].removesuffix(".git").rstrip("/")


def violations(path, text, names, repository):
    results = []
    identity = re.compile(
        "|".join(
            re.escape(part) for name in names for part in name.split() if len(part) > 2
        ),
        re.I,
    )
    public_link = re.compile(
        r"(?:https://)?"
        + re.escape(repository.removeprefix("https://"))
        + r"(?:\.git)?(?![A-Za-z0-9_.-])(?:/[^\s\x22\x27<>)]*)?"
    )
    for number, line in enumerate(text.splitlines(), 1):
        visible = public_link.sub("", line)
        attribution = path == "pyproject.toml" and any(
            re.fullmatch(
                r"\s*\{\s*name\s*=\s*" + re.escape(json.dumps(name)) + r"\s*\},?\s*",
                line,
            )
            for name in names
        )
        if (
            names
            and path not in LEGAL_NOTICES
            and not attribution
            and identity.search(visible)
        ):
            results.append((number, "personal-reference"))
        if PERSONAL_PATH.search(visible):
            results.append((number, "personal-path"))
        for address in LAN.findall(visible):
            if not (path.startswith("tests/") and address in FIXTURE_ADDRESSES):
                results.append((number, "private-address"))
    return sorted(set(results))


def message_violations(text, names, repository):
    # Standaard merge-metadata mag het reeds publieke repositoryaccount bevatten.
    owner = urlsplit(repository).path.strip("/").split("/")[0]
    normalized = text.replace("from " + owner + "/", "from contributor/")
    found = violations("commit-message", normalized, names, repository)
    lines = text.strip().splitlines()
    if not lines or not (
        SUBJECT.fullmatch(lines[0])
        or lines[0].startswith(("Merge pull request #", "Merge branch ", 'Revert "'))
    ):
        found.append((1, "commit-subject"))
    for number, line in enumerate(lines, 1):
        if INTERNAL_TICKET.search(line):
            found.append((number, "private-tracker-reference"))
        if CONVERSATION.search(line):
            found.append((number, "conversation-note"))
    return sorted(set(found))


def private_file(name):
    path = Path(name)
    return (
        any(
            part in {".pi", ".claude", ".codex", ".private", "node_modules", ".venv"}
            for part in path.parts
        )
        or path.name == ".env"
        or path.name.endswith((".env", ".db", ".db-wal", ".db-shm", ".key", ".pem"))
        or name.startswith("src/betonning/static/")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message-file", type=Path)
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    names, repository = settings(root)
    paths = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    findings = []
    for name in sorted(set(filter(None, paths))):
        path = root / name
        if private_file(name):
            findings.append({"file": name, "rule": "private-or-generated-file"})
            continue
        if path.is_symlink():
            findings.append({"file": name, "rule": "symlink"})
            continue
        if not path.is_file():
            continue
        try:
            body = path.read_text()
        except UnicodeDecodeError:
            continue
        findings.extend(
            {"file": name, "line": line, "rule": rule}
            for line, rule in violations(name, body, names, repository)
        )
    if args.message_file:
        findings.extend(
            {"file": "commit-message", "line": line, "rule": rule}
            for line, rule in message_violations(
                args.message_file.read_text(), names, repository
            )
        )
    if args.history:
        log = (
            subprocess.check_output(
                ["git", "log", "--all", "--format=%H%x00%B%x00"], cwd=root
            )
            .decode()
            .split("\0")
        )
        for index in range(0, len(log) - 1, 2):
            revision, message = log[index].strip(), log[index + 1]
            findings.extend(
                {"commit": revision, "line": line, "rule": rule}
                for line, rule in message_violations(message, names, repository)
            )
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    raise SystemExit(bool(findings))


if __name__ == "__main__":
    main()
