"""Deploy een schone Hegemone-commit naar een reeds geconfigureerde native service."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile

from native_release_remote import validate_profile


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True)
    if result.returncode:
        raise RuntimeError("Deploymentstap mislukt: " + args[0])
    return result.stdout


def pack_release(root, destination):
    if run(["git", "status", "--porcelain"], cwd=root).strip():
        raise ValueError("Commit eerst de codewijzigingen")
    revision = run(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    stamp = int(run(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=root))
    source = run(["git", "archive", "--format=tar", "HEAD"], cwd=root)
    destination.write_bytes(source)
    static = root / "src/betonning/static"
    if (
        not (static / "index.html").is_file()
        or not (static / "third-party-licenses.txt").is_file()
    ):
        raise ValueError("Bouw eerst de frontend inclusief notices")
    with tarfile.open(destination, "a") as bundle:
        for path in sorted(static.rglob("*")):
            if path.is_symlink():
                raise ValueError("Symlinks in de frontendbuild zijn niet toegestaan")
            if path.is_file():
                info = tarfile.TarInfo(path.relative_to(root).as_posix())
                content = path.read_bytes()
                info.size, info.mode, info.mtime = len(content), 0o644, stamp
                bundle.addfile(info, io.BytesIO(content))
    return revision, hashlib.sha256(destination.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Stop/backup/switch/start van de bestaande appservice",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.profile.resolve().is_relative_to(root):
        raise ValueError("Bewaar het private deploymentprofiel buiten de repository")
    profile = validate_profile(json.loads(args.profile.read_text()))
    if run(["git", "status", "--porcelain"], cwd=root).strip():
        raise ValueError("Commit eerst de codewijzigingen")
    print("Frontend uit Hegemone bouwen", flush=True)
    run(["npm", "ci", "--no-audit", "--no-fund"], cwd=root / "ui")
    run(["npm", "run", "build"], cwd=root / "ui")
    if (root / "docs/hegemone/FRONTEND_LICENSES.txt").read_bytes() != (
        root / "src/betonning/static/third-party-licenses.txt"
    ).read_bytes():
        raise ValueError(
            "De gebouwde licentienotices wijken af van de gereviewde snapshot"
        )
    with tempfile.TemporaryDirectory(prefix="hegemone-native-") as directory:
        archive = Path(directory) / "release.tar"
        revision, digest = pack_release(root, archive)
        remote_root = profile["root"]
        mkdir = (
            "mkdir -p "
            + shlex.quote(remote_root + "/staging")
            + " "
            + shlex.quote(remote_root + "/operations")
        )
        run(["ssh", "-o", "BatchMode=yes", profile["host"], mkdir])
        run(
            [
                "scp",
                "-q",
                str(archive),
                profile["host"] + ":" + remote_root + "/staging/" + digest + ".tar",
            ]
        )
        helper = remote_root + "/operations/native_release_remote.py"
        run(
            [
                "scp",
                "-q",
                str(root / "tools/native_release_remote.py"),
                profile["host"] + ":" + helper,
            ]
        )
        encoded = base64.b64encode(json.dumps(profile).encode()).decode()
        command = [
            "python3",
            helper,
            "--config",
            encoded,
            "--revision",
            revision,
            "--digest",
            digest,
        ]
        if args.activate:
            command.append("--activate")
        output = run(
            ["ssh", "-o", "BatchMode=yes", profile["host"], shlex.join(command)]
        )
        print(output.decode().strip())


if __name__ == "__main__":
    main()
