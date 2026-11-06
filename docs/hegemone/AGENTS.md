# Working on Hegemone

Hegemone is a FastAPI/sqlite3 application with a Svelte UI. The Python package
retains the name `betonning` for compatibility. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

- API routers call repository functions; repositories contain data access and
  take a connection first. Keep multi-write operations atomic.
- MCP is an HTTP client. Do not import repository or database modules there.
- Keep identifiers, API fields, enums, refs and stored content stable. UI copy
  belongs in the shared English/Dutch catalogs. Server output language and AI
  output language are separate installation settings.
- Preserve human-only actions, preview/confirmation gates, scopes, CSRF, resource
  limits, webhook signing and target validation when changing a flow.
- Use temporary fixture data for tests. Run targeted checks while implementing;
  report what actually ran. Build and inspect affected UI states when they change.
- Never print or commit credentials, local databases, attachments, browser auth
  state or private deployment configuration. Use application APIs for live data.
- Keep source comments consistent with the surrounding module; older comments
  and docstrings may be Dutch. Write public documentation in English.
- Do not send messages, publish a release or modify external infrastructure
  without the authorization needed for that concrete action.

Agent integration instructions are in [AGENT_SETUP.md](AGENT_SETUP.md). The license
is GPL-3.0-only; preserve attribution and describe material AI assistance and
verification in reviewable changes.


## Source of truth and deployments

Make application changes in this Hegemone repository. A predecessor/private
workspace may be retained for history or operational notes; do not develop a
second application copy there. Keep instance-specific SSH targets, service names,
paths and secret configuration in private profiles outside this checkout. Use
[NATIVE_DEPLOYMENT.md](NATIVE_DEPLOYMENT.md) for already configured native services.


## Public/private boundary

Follow [PUBLIC_BOUNDARY.md](PUBLIC_BOUNDARY.md) for every comment, fixture, commit,
PR and document. Use professional technical explanations. Keep personal requests,
private conversations/identities/operations and private tracker references out of
public commit messages. Use synthetic actors; preserve only intentional package
attribution, legal notices and public project links. Private notes live outside
this repository. Run the public-boundary check and inspect the complete diff/body.
A cleanup commit does not sanitize earlier reachable revisions.
