# Public information and private notes

Everything in Git — including commit bodies, old revisions, comments, fixtures,
screenshots and PR descriptions — must be suitable for public distribution.

## Public material

Describe the technical problem, relevant constraints, resulting behavior and
verification. Explain why code behaves as it does. Use roles such as user,
maintainer or agent, and clearly fictional test actors such as `person`.

Use professional Conventional Commit summaries, for example:
`fix(api): validate ticket filter input`. Bodies explain behavior and evidence.
Reference publicly accessible issues when useful. Private tracker identifiers,
conversations with the maintainer, personal requests and diary-style notes do
not belong in commit messages or PR descriptions.

Public project links and intentional package authorship are professional metadata,
not permission to add personal context. Preserve legal copyright and third-party
license notices. Use a public or noreply Git identity rather than a private email.
AI assistance must remain transparently described in the README.

## Private material

Keep personal preferences, anecdotes, chat transcripts, private ticket content,
private contacts, local usernames/home directories, actual deployment targets,
credentials, databases and operational reports outside this repository. Private
notes belong in the private issue tracker or in a separate private notes/profile
directory. An ignored file inside this checkout is not a publication boundary.
Never copy private memory or a private handoff into public docs or commit bodies.

For examples use reserved documentation domains and addresses. Network security
tests may use the two explicitly synthetic private addresses recognized by the
boundary checker, only under `tests/`. They must not represent a real deployment.
Production users, tickets and stored content are not renamed or rewritten by
repository cleanup.

## Checks and review

Run `uv run python tools/check_public_boundary.py --history` from a Git checkout before publication.
Source archives intentionally omit `.git`; verify their accompanying SHA256 and
`SOURCE_MANIFEST.json` instead. The checker exits with a clear requirement message
when run from an archive and never scans an unrelated parent repository.
The checker reports paths/rule identifiers, never matched private text. It checks
maintainer-name leakage outside narrow legal/package attribution, home paths,
private addresses, tracked private/generated files and commit-message hygiene.
CI checks the full public history. A local commit-message hook can be installed
with `git config core.hooksPath .githooks`.

The check complements secret scanning and human review. Confirm that examples
are fictional, screenshots contain no real account data, and links are public.
Check new files and the complete commit body, not only the subject. A new commit
does not remove private content from an older reachable revision. If unpublished
history needs sanitizing, retain rollback material privately and publish only
the reviewed clean history. Never force-push a published history without approval.
