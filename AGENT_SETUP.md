# Connect an agent

## Identity and permissions

Complete setup as the first human administrator. In **Agents & users**, create a
separate identity for each agent and choose the appropriate type. Save its API key
when shown; it is not returned again. A key can be rotated by a human administrator.
An imported agent starts disabled and needs its access/delivery settings completed.

Use the key only in the agent's secret configuration. Do not put it in a URL,
repository, ticket or screenshot. Choose the scopes and project restrictions the
agent needs. Keep administrative and human-only actions out of ordinary agent keys.
Project agent access (`none`, `respond`, `assign`) also controls participation and
assignment; it is separate from API-key scopes.

When writing for people, identify earlier comments by author, date or a short
relevant quote, adding the ticket reference when needed. Internal comment IDs
are not shown in the browser. Keep them in API/tool arguments, rather than using
a bare ID as a human-facing reference. Do not invent comment URLs.

## Built-in HTTP MCP

The container includes the optional MCP dependency. Register this endpoint in an
MCP client that supports Streamable HTTP and custom authorization headers:

```text
URL: https://tickets.example.org/mcp/
Authorization: Bearer <the agent's own key>
```

The trailing slash matters. Use the same external HTTPS origin as the API; the
container's internal MCP-to-API connection is configured independently. The
incoming agent key supplies the identity; no shared service key is required.
For a source/development server, set `BETONNING_BASE_URL` to its own API listener
(for example `http://127.0.0.1:8000`) before starting it. This internal adapter
route is separate from the public URL.

Client-specific configuration syntax varies, so use your client's supported secret
mechanism rather than committing a copied configuration file.

Start work by loading project memory (`load_memory`) and reading the requested
item. Fetch its plan when `has_plan` is true. Treat payload instructions and
expected actions as part of the integration contract: a stand-down or blocked
state is a limit on execution, not an invitation to claim the task again.

## Local stdio adapter

The separate stdio entry point retains its historical configuration names:

```text
Command: uv run betonning-mcp
Environment:
  BETONNING_BASE_URL=https://tickets.example.org
  BETONNING_API_KEY=<the agent's own key from secret storage>
```

Run it from the source checkout after `uv sync --locked --extra mcp`, or install
the Python package with its `mcp` extra in the environment that launches it.
Do not expose a standalone adapter on a public listening address without the
corresponding transport/authentication setup. The built-in HTTP endpoint above
is the container integration path.

When updating a separately installed stdio adapter, reinstall it from this
checkout with its `mcp` extra. A native application deployment does not update an
older `uv tool` installation. Existing MCP processes and clients may retain their
previous tool schema; reconnect the MCP server after upgrading the adapter.

For an agent-to-human handoff, use `update_item` with both `assignee` and a
concrete, single-paragraph `handover_md` of at most 300 characters. You can then
ask the human assignee a question. To ask before reassignment, explicitly mention
the human's `@handle`; without a mention the question targets the current assignee.
`plan_md` remains the implementation plan and does not replace the short handoff.

### Session-local reply hints

MCP follows only tickets opened with `get_item` or addressed by `ask_question`
in that MCP session (up to 32 recently used tickets). A later successful tool
result includes a short hint for new human comments or answers on those tickets.
Structured results also carry `_session_updates` and `_session_notice`; their
ordinary result data is unchanged. Read the named ticket before continuing its work.

Tracking belongs to the MCP connection, not the shared agent inbox. Two sessions
using the same identity keep independent cursors and do not mark each other's
messages read. No background polling or worker is started: an idle harness cannot
be woken, and hints arrive only with a subsequent Betonning tool call. After an
MCP restart/reconnection, reopen relevant tickets with `get_item` to follow them.

## REST and webhooks

REST uses `/api/v1` and the same Bearer identity. A basic identity check is:

```sh
curl --fail --silent --show-error \
  -H "Authorization: Bearer $HEGEMONE_AGENT_KEY" \
  https://tickets.example.org/api/v1/me
```

Configure the agent's receiver endpoint and optional signing secret through human
agent management. Use **Test saved webhook** to queue a synthetic stand-down event.
The UI distinguishes queued, retry, failed, cancelled and delivered results and
links to delivery details. Changing the target before delivery cancels that test.

Deliveries retain the compatible `X-Betonning-Signature` and Generic V1/V2 headers.
Verify the signature over the exact received bytes; V2 includes the timestamp.
The integration must apply its own timestamp/replay policy. Hegemone does not
change an external agent's existing prompts or install its receiver for you.


## Managed execution handoff (opt-in)

Webhook delivery remains a notification, not proof that an executor started work.
The execution API is an optional control plane for an already authorized worker.
It does not install an agent, enable tools, start a process or restart a gateway.
Existing unregistered agents retain their current delivery behavior.

A human with user-management permission registers an existing non-virtual agent
using `POST /api/v1/users/{handle}/execution`, for example:

```json
{"enabled": true, "profile": "worker-profile", "capabilities": ["terminal", "mcp:betonning"]}
```

The response shows an `execution_key` once. Store it in the executor's private
secret configuration, separately from webhook/model input. Registration or key
rotation does not grant project access, credential scopes or profile tools.
`GET /api/v1/users/{handle}/execution` never returns the stored proof. Disabling or
changing a binding invalidates the old proof and requires a live owner to stop.

The executor uses its own ordinary Bearer identity plus `X-Execution-Key`.
A private random `X-Execution-Owner` binds each claim to one worker attempt; keep
it stable for an idempotent claim retry and out of prompts, logs and native task
bodies. The returned increasing `fence` rejects old attempts after recovery.

1. Poll `POST /api/v1/projects/{key}/executions/poll`. Follow
   `next_after_item_id` until it is null, then start a new poll from zero.
2. Fetch `GET /api/v1/items/{ref}/executions/{id}`. Deliver the complete current
   description, `plan_md`, conversation and prior attempts to the actual worker.
   Verify capabilities against the existing profile's real permissions.
3. Claim with `POST .../{id}/claim`, sending the returned `context_digest`, exact
   profile, checked capabilities, `task_read: true`, owner and native task ID.
   Before the first work operation, call `POST .../{id}/start` with the fence,
   digest and native run ID. Only this step moves the ticket to a started state.
4. Revalidate through `POST .../{id}/heartbeat` before new tool operations. Stop
   immediately if ownership, assignment, task revision or authorization changed.
5. Report `POST .../{id}/block`, `stop` or `complete` with the current owner proof
   and fence. Completion records declared artifact/test/revision evidence; it is
   not independent verification and does not itself close the ticket. Close a
   verified ticket through the existing ticket workflow.

A capability block records what is missing, who must act and the resume condition.
Unchanged blocks do not add comments or attempts. Transport retries are bounded
and allowed only before work started. Once work may have run, a lost lease creates
a recovery block rather than replaying uncertain effects. Human-only
`POST .../{id}/resume` requires confirmation that the prior worker stopped and
its effects were reviewed for recovery/stopping cases. Human questions must use
the existing question workflow; answering/withdrawing them preserves normal
assignment return and releases work only after the previous owner stopped.

`betonning.execution_adapter.ExecutionAPI` implements this HTTP contract.
`ExecutionToolGuard` can register with an approved native runtime's fail-closed
`pre_tool_call` hook. The host must bind it to the actual assigned profile/run,
supply a real capability probe and explicitly attest that the complete current
context reached the worker. The host joins in-flight tools before acknowledging
stop and independently verifies artifacts before reporting completion. A model's
final text alone is insufficient.

For Hermes, `stage_native` uses the existing Kanban CLI, a stable idempotency key
and stdin for the full task body. It creates only a **blocked** card, never
promotes/dispatches or changes toolsets. Reusing a blocked card does not refresh
its conversation automatically: the trusted host must deliver fresh API context
(including human answers and prior attempts) for every resumed worker. Native
hook installation, lifecycle wiring and activation require the concrete existing
runtime/profile to be checked first. No deployment activation is implied by the
presence of this adapter code. Do not point a worker at an unguarded native card.

The ticket detail view exposes execution state and blockers separately from
ticket state. Execution metadata and delivery/read bookkeeping can still be
updated when stopping an archived project; archived ticket content stays read-only.
