# Release verification — 0.1.0

## Separate clean-install review

On 2026-11-06, a separate test agent used only the reviewed source archive and
its README, in a new directory and an isolated local Docker project/volume.
It used its own synthetic administrator and agent; no production data, existing
configuration or mocked author fixtures were reused. Browser checks were headless.

The review passed:

- Container build, health, non-root UID/GID 10001 and read-only root filesystem.
- English first start and Dutch switch; one-time key-save confirmation.
- Reload-resumable onboarding and first project without an AI provider.
- Six canonical columns and three canonical work classes.
- Real ticket CRUD, progress, comments, archive/restore and disposable-ticket deletion.
- Language change preserving ticket data; installation and agent management.
- Anonymous access denied and agent denied human installation settings.
- Frontend license text and inventory available.
- Real authenticated MCP initialize, tool listing and ticket retrieval.
- Setup-token removal and container recreation, preserving data, completed
  onboarding, a fresh key login and the existing browser session.

The reviewed application-source revision is
[`c987fe0`](https://github.com/sanderdatema/hegemone/commit/c987fe0dc6e9132ec7cfd6bebf955b2e38eff66b).
Subsequent release edits clarify documentation and archive-checker behavior;
application/runtime code is unchanged. Archive revision metadata was independently
confirmed in the standard Git archive PAX header.

The review found no application install/runtime defect. Two distribution notes
were addressed: a detached source manifest/checksum set accompanies the release,
and the publication checker now clearly requires a Git checkout instead of
raising an archive traceback or finding an unrelated parent repository.

## Automated release gates

The [verification workflow](https://github.com/sanderdatema/hegemone/actions/workflows/hegemone.yml)
runs on the release revision. It covers lint, typechecking, source/commit privacy,
locked Python/npm dependency policy, translation checks, full backend/frontend
tests, frontend build and license snapshot, Compose validation, exact Docker
context, image build and the runtime smoke test.

The smoke test covers health, preserved notices, non-root writable data, fresh
setup/onboarding, authenticated MCP/model mapping, ticket progression, encrypted
provider configuration, stopped-volume backup/restore with ownership and saved
keys/content, and a synthetic schema-51 upgrade preserving identity/access/plan.
Inspect the actual workflow result for the exact commit or release tag.

## Artifact identity and limits

The release provides source, `SHA256SUMS` and `SOURCE_MANIFEST.json`. The manifest
contains the public commit/tree identifiers, source archive hash and individual
file hashes, without local paths or private operational data. Git metadata is
not needed to install the application from an archive; source/history policy
checks are developer/publisher commands for a Git checkout.

The separate review used Linux/arm64 containers. Other release-platform coverage
comes from the named CI runner and should not be inferred to cover all systems.
Real external AI providers and third-party webhook receivers were not used in the
separate install review; those integrations require the operator's configuration.
Transport/security behavior has dedicated automated regression tests. No human
penetration test, security certification or universal platform claim is made.
