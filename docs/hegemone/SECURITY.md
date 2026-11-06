# Security and verification

Hegemone is under active development. The first public release has not yet been
verified end to end. Do not treat a working development build as a production
security certification.

## Checks performed

Development has included security review and remediation of authentication,
browser sessions and CSRF, API-key scopes, wiki permissions, webhook destination
validation, uploads, resource budgets, MCP sessions and live SSE revocation.
The repository contains behavioral regression tests for these areas, including
`tests/test_security_*.py`, `tests/test_body_limit.py` and browser regressions under
`ui/e2e/`. Setup and resumable onboarding have also been tested against an empty
local database and through the browser. Focused upgrade/restore tests cover schema
51 data preservation and a stopped-directory backup containing attachments,
comments, wiki data and onboarding state. Local Linux/arm64 container checks also verified volume ownership, encrypted-key
restore, fresh setup/API/MCP and a synthetic schema-51 upgrade. These point-in-time
checks do not substitute for the final candidate or independent installation review.

For the private source revision used to prepare the public distribution, Gitleaks
8.30.1 reported no findings across 931 reachable commits and a tracked-file
snapshot. That result does not clear the private history for publication: privacy
references were found separately, and the public export must be audited again.
Only a new Git history will be published.

Dependency audits and source scans are point-in-time checks. Repeat them for the
exact release candidate. No independent penetration test or security certification
is claimed. The intended CI workflow is included in source; its presence alone
is not evidence that a particular build has passed.

## Before public release

The public source export, dependency/asset licensing, complete localization,
container runtime, fresh installation, upgrade and backup-restore checks must
be verified for the release candidate. Publicly available source must never
include production databases, attachments, keys or private deployment history.

## Reporting a vulnerability

Do not put API keys, private ticket data or exploit details in a public issue.
Private vulnerability reporting is enabled on the public GitHub repository.
Use [Report a vulnerability](https://github.com/sanderdatema/hegemone/security/advisories/new)
for private security reports. This project does not yet offer a supported public
release or a guaranteed response time.

## Dependency audit policy

CI audits the locked Python runtime (including MCP) and all npm dependencies.
The npm gate rejects every finding except the current low-severity build-only
chain for [GHSA-gcqx-w48m-w2h4](https://github.com/advisories/GHSA-gcqx-w48m-w2h4):
`deepmerge@4.3.1`, `@sveltejs/vite-plugin-svelte` and its inspector.
As checked on 2026-11-06, the advisory lists no patched version. The installed
plugin uses deepmerge to merge repository-owned Vite/Svelte build configuration;
this is not a path for application ticket or API input. The runtime container
copies the static frontend output, without Node or its build dependencies.
Builds must use reviewed configuration; do not build untrusted configuration
with secrets available. This exception does not establish that upstream code is
safe for arbitrary inputs.

The gate verifies that affected lockfile entries remain development-only, the
advisory and severity match, and npm reports no available fix. A changed advisory,
a runtime dependency, or an available repair fails CI and requires reassessment.
