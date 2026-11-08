"""Expliciet Docker-bronmanifest en onafhankelijke contextfixture zonder secrets.

Na toevoegen/verwijderen van runtimebron: --generate; CI gebruikt standaard de
read-only vergelijking en een scratch-build met publieke/private sentinels.
"""

import argparse
from pathlib import Path
import json
import subprocess
import tempfile

DOCS = [
    "README.md",
    "USER_GUIDE.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "SUPPORT.md",
    "CHANGELOG.md",
    "AGENT_SETUP.md",
    "AGENTS.md",
    "THIRD_PARTY.md",
    "NATIVE_DEPLOYMENT.md",
    "PUBLIC_BOUNDARY.md",
    "RELEASE_VERIFICATION.md",
    "FRONTEND_LICENSES.txt",
    "screenshots/board-en.png",
    "screenshots/board-nl.png",
]


def build_files(root):
    names = {
        "Dockerfile",
        "LICENSE",
        "pyproject.toml",
        "uv.lock",
        "ui/package.json",
        "ui/package-lock.json",
        "ui/index.html",
        "ui/vite.config.js",
        "src/betonning/py.typed",
        "src/betonning/api_errors.json",
        "src/betonning/outbound_messages.json",
    }
    names.update("docs/hegemone/" + name for name in DOCS)
    for directory, suffixes in [
        ("src/betonning", {".py", ".sql"}),
        ("ui/src", {".svelte", ".js", ".ts", ".css", ".svg"}),
        ("ui/public", {".svg"}),
    ]:
        for path in (root / directory).rglob("*"):
            relative = path.relative_to(root)
            if any(
                part.startswith(".")
                or part in {"static", "__pycache__", "node_modules"}
                for part in relative.parts
            ):
                continue
            if (
                path.is_file()
                and path.suffix in suffixes
                and not path.name.endswith(".test.js")
            ):
                names.add(relative.as_posix())
    for name in names:
        candidate = root / name
        if any(
            part.is_symlink()
            for part in [candidate, *candidate.parents]
            if part != root.parent
        ):
            raise ValueError("Symlink in buildbron niet toegestaan")
        if not candidate.is_file():
            raise ValueError("Verplicht buildbestand ontbreekt")
        if any(char in name for char in "*?[]!\\"):
            raise ValueError("Niet-letterlijk buildpad")
    return sorted(names)


def policy(names):
    return (
        "# Gegenereerd met tools/audit_build_context.py --generate.\n# Alleen expliciete publieke buildbestanden; geen directory-uitzonderingen.\n**\n"
        + "".join("!" + name + "\n" for name in names)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    public = build_files(root)
    expected = policy(public)
    if args.generate:
        (root / ".dockerignore").write_text(expected)
        print(json.dumps({"generated": True, "files": len(public)}))
        return
    if (root / ".dockerignore").read_text() != expected:
        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": "manifest-outdated",
                    "action": "run tools/audit_build_context.py --generate",
                }
            )
        )
        raise SystemExit(1)
    private = [
        ".git/config",
        ".env",
        "betonning.db",
        "deploy/private.service",
        "private.key",
        "src/betonning/local.key",
        "src/betonning/local.json",
        "src/betonning/.private/code.py",
        "src/betonning/.pytest_cache/CACHEDIR.TAG",
        "src/betonning/__pycache__/secret.pyc",
        "src/betonning/local.env",
        "src/betonning/local.db",
        "src/betonning/static/private.js",
        "ui/node_modules/private.json",
        "ui/src/private.key",
        "ui/src/.private/hidden.js",
        "ui/src/local.db",
        "ui/src/test.test.js",
    ]
    with tempfile.TemporaryDirectory(prefix="hegemone-context-") as directory:
        folder = Path(directory)
        context = folder / "source"
        context.mkdir()
        for path in public + private:
            target = context / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "PRIVATE_SENTINEL" if path in private else "PUBLIC_SENTINEL"
            )
        (context / ".dockerignore").write_text(expected)
        recipe = folder / "audit.Dockerfile"
        recipe.write_text("FROM scratch\nCOPY . /\n")
        output = folder / "result"
        result = subprocess.run(
            [
                "docker",
                "build",
                "--file",
                str(recipe),
                "--output",
                "type=local,dest=" + str(output),
                str(context),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            print(json.dumps({"ok": False, "stage": "context-build"}))
            raise SystemExit(1)
        actual = {
            path.relative_to(output).as_posix()
            for path in output.rglob("*")
            if path.is_file()
        }
        if actual != set(public):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "missing": sorted(set(public) - actual),
                        "unexpected": sorted(actual - set(public)),
                    }
                )
            )
            raise SystemExit(1)
        print(
            json.dumps(
                {
                    "ok": True,
                    "public_files": len(public),
                    "private_paths_excluded": len(private),
                }
            )
        )


if __name__ == "__main__":
    main()
