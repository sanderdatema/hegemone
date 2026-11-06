# Support and compatibility

Hegemone's first public release is still in preparation. There is no published
supported release or response-time commitment yet. Source files and a CI
configuration do not by themselves prove that a release candidate passed.

| Area | Target | Verification status |
| --- | --- | --- |
| Container | Linux, Docker Engine and Compose v2 | Clean local arm64/Linux candidate built; setup/API/MCP and synthetic restore verified; independent review remains |
| Source backend | Python >=3.12, uv, SQLite | Clean-candidate Python 3.12 backend run and targeted corrections checked; GitHub CI configured but not yet run |
| Frontend build | Node.js 22, npm lockfile | 1,075 frontend tests, production build and affected browser flows checked; Node.js 22 container build verified |
| Data upgrade | Existing SQLite schema, numbered migrations | Synthetic schema-51 upgrade checked natively and in the clean local Linux container; independent review remains |
| Backups | Stopped complete data directory plus persistent secret configuration | Native and Linux-container restore fixtures checked, including ownership and saved keys; independent review remains |
| Windows native | No supported native procedure declared | Not verified |

Run one application worker. Background tasks, in-memory request budgets and live
session handling assume one process. A reverse proxy is required for public HTTPS;
Compose binds the application port to loopback by default.

AI providers, webhook agents, Telegram and MCP are optional integrations. Without
an AI provider, ticket management still works. Configure integrations explicitly
and check the actual receiver/provider version you operate. A webhook test proves
that a synthetic event was accepted; it does not prove that an agent will execute
all future tasks correctly.

Historical Python package/CLI names, some payload keys and workflow markers are
retained for compatibility. See [AGENT_SETUP.md](AGENT_SETUP.md). Public UI and new
server-generated text default to English, with Dutch supported. Existing content
and protocol values are preserved.

Before upgrading, read [CHANGELOG.md](CHANGELOG.md), make a consistent backup and
retain the encryption material for saved provider keys. Test the upgrade and
restore on a separate copy. Security scope and reporting are in
[SECURITY.md](SECURITY.md).
