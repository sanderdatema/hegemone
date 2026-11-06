"""Publieke tekst blijft zakelijk; detectierapporten bevatten geen gevonden inhoud."""

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "public_boundary", Path(__file__).parents[1] / "tools/check_public_boundary.py"
)
boundary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(boundary)
AUTHORS = ["Alex Maintainer"]
REPOSITORY = "https://github.com/alex-maintainer/project"


def test_private_identity_not_allowed_in_comments_or_fixtures():
    for path in ["src/api.py", "tests/test_example.py", "README.md"]:
        assert boundary.violations(
            path, "Alex asked for this behavior", AUTHORS, REPOSITORY
        ) == [(1, "personal-reference")]
    assert (
        boundary.violations(
            "src/api.py", "# Human approval is required", AUTHORS, REPOSITORY
        )
        == []
    )


def test_authorship_exception_is_narrow_and_project_links_are_public():
    assert (
        boundary.violations(
            "pyproject.toml", '    { name = "Alex Maintainer" }', AUTHORS, REPOSITORY
        )
        == []
    )
    assert boundary.violations(
        "pyproject.toml",
        '    { name = "Alex Maintainer", email = "private@example.invalid" }',
        AUTHORS,
        REPOSITORY,
    )
    assert (
        boundary.violations(
            "README.md",
            "[github.com/alex-maintainer/project](" + REPOSITORY + ")",
            AUTHORS,
            REPOSITORY,
        )
        == []
    )
    assert boundary.violations(
        "README.md", REPOSITORY + "-personal", AUTHORS, REPOSITORY
    )
    assert boundary.violations(
        "README.md", "https://alex-maintainer.example.invalid", AUTHORS, REPOSITORY
    )


def test_legal_notices_keep_authors_but_do_not_allow_private_paths():
    assert (
        boundary.violations(
            "FRONTEND_LICENSES.txt", "Copyright Alex Maintainer", AUTHORS, REPOSITORY
        )
        == []
    )
    private = "/" + "Users/private-user/notes"
    assert boundary.violations(
        "FRONTEND_LICENSES.txt", private, AUTHORS, REPOSITORY
    ) == [(1, "personal-path")]
    assert boundary.violations(
        "docs/other-notice.md", "Alex Maintainer", AUTHORS, REPOSITORY
    )


def test_private_addresses_only_have_explicit_synthetic_fixture_exceptions():
    synthetic = ".".join(map(str, (10, 23, 45, 67)))
    other = ".".join(map(str, (192, 168, 99, 99)))
    assert (
        boundary.violations("tests/test_network.py", synthetic, AUTHORS, REPOSITORY)
        == []
    )
    assert boundary.violations("src/api.py", synthetic, AUTHORS, REPOSITORY) == [
        (1, "private-address")
    ]
    assert boundary.violations("tests/test_network.py", other, AUTHORS, REPOSITORY) == [
        (1, "private-address")
    ]


@pytest.mark.parametrize(
    "text,rule",
    [
        ("fix(api): guard input\n\nAlex asked for this.", "personal-reference"),
        ("fix(api): guard input\n\nZoals je vroeg, aangepast.", "conversation-note"),
        ("fix(api): guard input (BETON-999)", "private-tracker-reference"),
        ("update stuff", "commit-subject"),
    ],
)
def test_commit_messages_reject_private_and_conversational_content(text, rule):
    assert rule in {
        kind for _, kind in boundary.message_violations(text, AUTHORS, REPOSITORY)
    }


def test_professional_message_and_public_issue_reference_are_allowed():
    assert (
        boundary.message_violations(
            "fix(api): valideer ticketfilters\n\nVoorkomt ongeldige verzoeken. Fixes #12.",
            AUTHORS,
            REPOSITORY,
        )
        == []
    )
    assert (
        boundary.message_violations(
            "Merge pull request #12 from alex-maintainer/validation",
            AUTHORS,
            REPOSITORY,
        )
        == []
    )


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        "config.env",
        "data.db",
        ".pi/private.md",
        "src/betonning/static/index.js",
    ],
)
def test_private_or_generated_files_are_rejected_by_name(name):
    assert boundary.private_file(name)


def test_scanner_does_not_follow_symlinks_or_print_private_text(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "repository"
    (root / "tools").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nauthors = [{ name = "Alex Maintainer" }]\n[project.urls]\nRepository = "https://github.com/alex-maintainer/project"\n'
    )
    target = tmp_path / "private-content"
    target.write_text("synthetic-private-value-must-not-be-read")
    (root / "public.py").symlink_to(target)
    monkeypatch.setattr(
        boundary, "__file__", str(root / "tools/check_public_boundary.py")
    )
    monkeypatch.setattr(
        boundary.subprocess, "check_output", lambda *args, **kwargs: b"public.py\0"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_public_boundary.py"],
    )
    with pytest.raises(SystemExit) as error:
        boundary.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert '"rule": "symlink"' in output
    assert "synthetic-private-value" not in output


def test_archive_reports_checkout_requirement_without_scanning_parent_repo(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "archive"
    (root / "tools").mkdir(parents=True)
    monkeypatch.setattr(
        boundary, "__file__", str(root / "tools/check_public_boundary.py")
    )

    def unexpected_git(*args, **kwargs):
        raise AssertionError("Een bovenliggende repository mag niet worden gescand")

    monkeypatch.setattr(boundary.subprocess, "check_output", unexpected_git)
    monkeypatch.setattr(sys, "argv", ["check_public_boundary.py"])
    with pytest.raises(SystemExit) as error:
        boundary.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "Git-checkout" in output.err
    assert "Traceback" not in output.err
