"""Controleer npm-audit met één begrensde uitzondering voor buildconfiguratie."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

ADVISORY = "https://github.com/advisories/GHSA-gcqx-w48m-w2h4"
BUILD_CHAIN = {
    "deepmerge",
    "@sveltejs/vite-plugin-svelte",
    "@sveltejs/vite-plugin-svelte-inspector",
}


def violations(report: dict, lock: dict) -> list[str]:
    """Weiger onbekende meldingen, productiegebruik en beschikbare reparaties."""
    if report.get("auditReportVersion") != 2 or "vulnerabilities" not in report:
        return ["Onbekend npm-auditformaat"]
    failures = []
    for name, entry in report["vulnerabilities"].items():
        allowed = (
            name in BUILD_CHAIN
            and entry.get("severity") == "low"
            and entry.get("fixAvailable") is False
            and bool(entry.get("nodes"))
            and bool(entry.get("via"))
        )
        for node in entry.get("nodes", []):
            package = lock.get("packages", {}).get(node, {})
            allowed = allowed and package.get("dev") is True
            if name == "deepmerge":
                allowed = allowed and package.get("version") == "4.3.1"
        for cause in entry.get("via", []):
            if isinstance(cause, str):
                allowed = allowed and cause in BUILD_CHAIN
            else:
                allowed = allowed and (
                    cause.get("url") == ADVISORY
                    and cause.get("severity") == "low"
                    and cause.get("name") == "deepmerge"
                )
        if not allowed:
            failures.append(name)
    return failures


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["npm", "audit", "--json"], cwd=root / "ui", capture_output=True, text=True
    )
    if result.returncode not in (0, 1):
        raise SystemExit("npm-audit kon niet worden uitgevoerd")
    try:
        report = json.loads(result.stdout)
        failures = violations(report, json.loads((root / "ui/package-lock.json").read_text()))
    except (ValueError, TypeError, KeyError):
        raise SystemExit("Ongeldige npm-auditrespons") from None
    if failures:
        raise SystemExit("Niet-toegestane dependencybevindingen: " + ", ".join(failures))
    print(json.dumps({"ok": True, "accepted_build_findings": sorted(report["vulnerabilities"])}))


if __name__ == "__main__":
    main()
