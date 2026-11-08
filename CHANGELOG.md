# Changelog

## Unreleased

- Add opt-in execution handoff with fenced claims, deduplicated blockers and explicit recovery; native runtime activation remains separate.

- Keep archived projects read-only across UI, API and background writes until restored.

- Search project codes and names directly in the project picker, including quiet projects.
- Correct board pagination when quick filters hide already loaded cards or a page is exhausted.
- Let humans mark open triage questions as not relevant while retaining their history.
- Guide AI-generated explanations toward readable comment references instead of internal IDs.
- Add an English user guide for daily workflows, configuration and troubleshooting.
- Make wiki context-budget tests deterministic when page timestamps are equal.

## 0.1.0 — 2026-11-06

Initial public source release.

- Hegemone branding, GPL-3.0-only licensing and explicit Claude Code/Codex credits.
- First-administrator setup with a dedicated token and resumable onboarding.
- Six default project columns and canonical routine/standaard/complex work classes.
- Versioned installation settings, write-only encrypted provider keys and controlled
  runtime updates with deployment overrides.
- English/Dutch interface, server-generated instructions and separate AI output language.
- Reviewed configuration import/export without credentials or ticket/wiki content.
- Configurable agents and explicit signed webhook connection tests through the delivery queue.
- Container/Compose packaging, clean-source export tooling and release verification work.

The clean local candidate has undergone source/privacy/license checks, frontend
and backend verification, and container setup/MCP/upgrade/restore checks. Bundled
frontend notices and Python runtime license files are preserved. A separate test agent completed the clean installation review; the release is
gated by the verification workflow on its revision. Source archives include
checksums and a detached revision/file manifest. Private development history is
excluded from the public distribution.
