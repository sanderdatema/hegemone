# Contributing to Hegemone

The first public distribution is being prepared. Check the current release
status in [SUPPORT.md](SUPPORT.md) before relying on an installation procedure.

## Development setup

Use Python 3.12 or later, Node.js 22 and uv. From the repository root:

```sh
uv sync --locked --extra mcp
npm ci --prefix ui --no-audit --no-fund
npm run build --prefix ui
uv run uvicorn betonning.server:app --reload
```

The Python package retains the name `betonning` for compatibility. The UI build
writes to `src/betonning/static/`. Run `npm run dev --prefix ui` for the Vite UI
with its local API proxy. Use an isolated development database and local secrets;
keep databases, credentials and generated build files outside commits.

## Changes and verification

Explain the concrete problem and resulting behavior. Add focused behavioral tests
when changing logic or fixing a regression. Run only the checks relevant to the
change during development; broad release checks belong to a specific candidate.
Examples:

```sh
uv run pytest tests/test_setup.py
npm test --prefix ui -- src/lib/notifications.test.js
npm run build --prefix ui
```

When adding or removing runtime source files, regenerate the explicit container
manifest with `uv run python tools/audit_build_context.py --generate`. The audit
without that flag checks the manifest and builds an isolated context fixture;
it requires a running local Docker Engine.

Record which checks actually ran and any remaining uncertainty. For a UI change,
check the affected flow in English and Dutch, including error and empty states.
Keep user content, refs, handles, API field names and stored enum values intact.

API routers call repository functions; repository functions use sqlite3 directly.
Keep multiple writes atomic. MCP tools communicate through HTTP and must not
import the repository or database layer. Read [AGENTS.md](AGENTS.md) for the
working conventions and [AGENT_SETUP.md](AGENT_SETUP.md) for integration setup.

## AI assistance and review

AI-assisted contributions are welcome. Describe material assistance where it
helps review, inspect the generated code and provide actual verification evidence.
Hegemone itself was built with Claude Code and OpenAI Codex;
[README.md](README.md) describes the checks performed during development.
Responsibility for the submitted change stays with its contributor and reviewers.

Submit code you have the right to contribute under GPL-3.0-only. Preserve upstream
copyright and license notices for included code or assets. Report suspected
vulnerabilities using [SECURITY.md](SECURITY.md), without publishing credentials,
private tickets or exploit details in an ordinary issue.


## Professional public communication

Follow [PUBLIC_BOUNDARY.md](PUBLIC_BOUNDARY.md). Commit messages and PR descriptions
explain the change and verification, without private conversations, personal
context or internal ticket references. Source comments explain behavior through
roles and technical constraints; fixtures use fictional people. Intentional
package authorship and required license notices are the only attribution
exceptions. Keep private operational notes and profiles outside the checkout.

Before committing, run `uv run python tools/check_public_boundary.py`. For a
publication candidate also use `--history`; CI does this automatically. Enable
the optional local message hook with `git config core.hooksPath .githooks`.
