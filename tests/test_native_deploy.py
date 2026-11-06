"""Native deploy: archiefgrens, profielvalidatie, backup en bronrollback."""

import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

TOOLS = Path(__file__).parents[1] / "tools"
_spec = importlib.util.spec_from_file_location(
    "native_release_remote", TOOLS / "native_release_remote.py"
)
remote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote)
sys.modules["native_release_remote"] = remote
_spec_driver = importlib.util.spec_from_file_location(
    "deploy_native", TOOLS / "deploy_native.py"
)
driver = importlib.util.module_from_spec(_spec_driver)
_spec_driver.loader.exec_module(driver)


@pytest.fixture
def profile(tmp_path):
    root, data = tmp_path / "code", tmp_path / "data"
    root.mkdir()
    data.mkdir()
    return {
        "host": "operator@host.example",
        "root": str(root),
        "data_dir": str(data),
        "service": "tickets.service",
        "user": "tickets",
        "python": "/usr/bin/python3.12",
        "health_url": "http://127.0.0.1:8000/health",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("host", "host;touch /tmp/x"),
        ("host", "-F"),
        ("root", "/etc/example"),
        ("data_dir", "/var/lib"),
        ("root", "/"),
        ("data_dir", "/var/../etc"),
        ("service", "--help"),
        ("user", "root"),
        ("health_url", "https://external.example/health"),
        ("health_url", "http://token@127.0.0.1/health"),
    ],
)
def test_rejects_unsafe_profile(profile, field, value):
    profile[field] = value
    with pytest.raises(ValueError):
        remote.validate_profile(profile)


def test_code_and_data_must_be_separate(profile):
    profile["data_dir"] = profile["root"] + "/data"
    with pytest.raises(ValueError):
        remote.validate_profile(profile)


@pytest.mark.parametrize(
    "name,kind",
    [
        ("normal.txt", "symlink"),
        ("../outside", "file"),
        (".env", "file"),
        (".git/config", "file"),
    ],
)
def test_rejects_unsafe_archive(tmp_path, name, kind):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as bundle:
        entry = tarfile.TarInfo(name)
        if kind == "symlink":
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
            bundle.addfile(entry)
        else:
            entry.size = 1
            bundle.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        remote.safe_extract(archive, tmp_path / "out")


def test_backup_preserves_content_excludes_older_backups_and_is_private(profile):
    data = Path(profile["data_dir"])
    (data / "fixture.db").write_bytes(b"synthetic-data")
    (data / "attachments").mkdir()
    (data / "attachments/image").write_bytes(b"synthetic-image")
    (data / "backups").mkdir()
    (data / "backups/old").write_bytes(b"not-recursive")
    config = data.parent / "private.env"
    config.write_text("SYNTHETIC_TEST=fixture")
    profile["config_paths"] = [str(config)]
    saved = remote.backup(profile, "abc123")
    assert saved.stat().st_mode & 0o777 == 0o600
    with tarfile.open(saved) as bundle:
        names = bundle.getnames()
        assert "data/fixture.db" in names and "data/attachments/image" in names
        assert not any("backups/" in name for name in names)
        assert bundle.extractfile("data/fixture.db").read() == b"synthetic-data"
        assert any(name.startswith("config/") for name in names)


def test_failed_start_rolls_back_source_without_replacing_live_data(
    profile, monkeypatch
):
    root, data = Path(profile["root"]), Path(profile["data_dir"])
    previous, release = root / "previous", root / "new-release"
    previous.mkdir()
    release.mkdir()
    (root / "current").symlink_to(previous)
    (data / "fixture.db").write_bytes(b"original")
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("systemctl", "show"):
            return (
                str(root / "current") if "WorkingDirectory" in args else profile["user"]
            )
        if args[:2] == ("systemctl", "start"):
            (data / "fixture.db").write_bytes(b"post-upgrade-write")
            raise RuntimeError("start failed")
        return ""

    monkeypatch.setattr(remote, "call", command)
    with pytest.raises(RuntimeError, match="vorige bron hersteld"):
        remote.activate(profile, release)
    assert (root / "current").resolve() == previous
    assert (data / "fixture.db").read_bytes() == b"post-upgrade-write"
    assert ("systemctl", "restart", profile["service"]) in calls


def test_release_packages_only_committed_source_and_built_frontend(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(
        ["git", "init", "--template="], cwd=root, check=True, capture_output=True
    )
    (root / "app.py").write_text('print("fixture")\n')
    (root / ".gitignore").write_text("src/betonning/static/\n.env\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / ".env").write_text("SYNTHETIC_TEST=not-in-archive")
    static = root / "src/betonning/static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<title>Hegemone</title>")
    (static / "third-party-licenses.txt").write_text("fixture license")
    archive = tmp_path / "release.tar"
    revision, digest = driver.pack_release(root, archive)
    assert len(revision) == 40 and len(digest) == 64
    with tarfile.open(archive) as bundle:
        assert ".env" not in bundle.getnames()
        assert "src/betonning/static/index.html" in bundle.getnames()
    (root / "app.py").write_text("uncommitted")
    with pytest.raises(ValueError, match="Commit eerst"):
        driver.pack_release(root, archive)
