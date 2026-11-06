"""De dependency-uitzondering mag geen nieuwe of productiebevindingen maskeren."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "dependency_audit", Path(__file__).parents[1] / "tools/audit_frontend_dependencies.py"
)
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)


def fixture():
    return {
        "auditReportVersion": 2,
        "vulnerabilities": {"deepmerge": {
            "severity": "low", "fixAvailable": False,
            "nodes": ["node_modules/deepmerge"],
            "via": [{"url": audit.ADVISORY, "severity": "low", "name": "deepmerge"}],
        }},
    }, {"packages": {"node_modules/deepmerge": {"version": "4.3.1", "dev": True}}}


def test_only_known_build_advisory_allowed():
    report, lock = fixture()
    assert audit.violations(report, lock) == []


@pytest.mark.parametrize("field,value", [
    ("severity", "moderate"), ("fixAvailable", True), ("nodes", []), ("via", []),
])
def test_changed_finding_rejected(field, value):
    report, lock = fixture()
    report["vulnerabilities"]["deepmerge"][field] = value
    assert audit.violations(report, lock)


def test_new_advisory_rejected():
    report, lock = fixture()
    report["vulnerabilities"]["deepmerge"]["via"][0]["url"] = "https://example.com/new"
    assert audit.violations(report, lock)


@pytest.mark.parametrize("field,value", [("dev", False), ("version", "4.3.2")])
def test_runtime_or_changed_version_rejected(field, value):
    report, lock = fixture()
    lock["packages"]["node_modules/deepmerge"][field] = value
    assert audit.violations(report, lock)


def test_unknown_package_and_failed_report_rejected():
    report, lock = fixture()
    report["vulnerabilities"]["unknown"] = report["vulnerabilities"].pop("deepmerge")
    assert audit.violations(report, lock)
    assert audit.violations({"error": {}}, lock)
