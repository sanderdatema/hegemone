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
