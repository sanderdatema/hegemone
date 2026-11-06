# Deploy to an existing native service

The primary standalone installation is Docker Compose. These tools support an
already configured single-process systemd deployment over SSH. They deploy
application releases; they do not provision hosts, users, networking or machines.
The remote host needs Python 3.12+, uv and systemd. Build the frontend locally
with the documented Node/npm versions.

Keep the host profile outside this repository. Example `deployment.json`:

```json
{
  "host": "root@host.example",
  "root": "/opt/hegemone",
  "data_dir": "/var/lib/hegemone",
  "service": "hegemone.service",
  "user": "hegemone",
  "python": "/usr/bin/python3.12",
  "health_url": "http://127.0.0.1:8000/health",
  "config_paths": ["/etc/hegemone", "/etc/systemd/system/hegemone.service"]
}
```

The existing unit must use `WorkingDirectory=/opt/hegemone/current` and start
`/opt/hegemone/current/.venv/bin/uvicorn betonning.server:app` with its existing
listener/options. Retain its non-root user, persistent data paths, hardening and
secret EnvironmentFiles. Its initial `current` symlink must identify the previous
working application so source rollback is possible. Application configuration must
come from the unit's private EnvironmentFiles; ignored checkout `.env` files are
not copied into release bundles. Preserve any required fallback settings during
this one-time operator configuration. No key should be printed or committed.

From a clean committed Hegemone checkout:

```sh
# Build, upload and install a release without interrupting the running service.
uv run python tools/deploy_native.py --profile /private/location/deployment.json

# Repeat preparation idempotently, then stop/backup/switch/start the app.
uv run python tools/deploy_native.py --profile /private/location/deployment.json --activate
```

The bundle contains committed source plus the freshly built static frontend and
license notices. The remote release records its commit and archive SHA256 in
`.hegemone-release.json`. Dependencies are locked and use the specified system
Python. Releases live under `root/releases`; `root/current` switches atomically.
The tool refuses dirty source, unsafe profile/archive paths, root application
users and unexpected service configuration.

Activation stops the existing service before archiving its complete data directory
and the explicitly listed configuration paths. Older `data_dir/backups` are
excluded to avoid recursive copies. Backups are root-private under that directory;
check disk capacity and retain them according to your private operations policy.
Health and the Hegemone HTML title are checked before reporting success. Verify
representative authenticated API/MCP operations and existing data separately.

If activation fails, the tool switches back to the previous source and restarts
the service. It does not overwrite live data or undo schema migrations. Review
migration compatibility before deployment; any database restore is a separate,
deliberate operation using the matching backup. Previous releases and staging
bundles are retained for operator inspection; prune them deliberately as needed.
