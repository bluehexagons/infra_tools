# Deploy Isolation: per-service users & managed persistence

> **Status:** Implemented for the **manifest** (`infra.json`) deploy path. The
> legacy detection path (Rails/node single shared `rails` user) is unchanged;
> migrating it is documented as future work below.

## Problem

Two gaps in the deploy path, surfaced while wiring `infra.json`:

1. **No user isolation.** The `setup ... --deploy` path runs *every* deployed
   site and service as one shared `rails` user (`remote_setup.py`,
   `deploy/deploy_steps.py`). A compromise in any one app can read/write every
   other app's files. (Other infra_tools components — `gogs`, the cicd
   `webhook`, `app_server_steps` — already use dedicated `--system` users; the
   deploy path just doesn't.)

2. **Inconsistent persistence.** Rails sites keep durable state in an
   infra_tools-managed root (`<base>/.infra_tools_shared/<app>/…`, symlinked into
   each release). The first cut of manifest services instead pushed data to an
   operator-managed `/opt/<name>/data`, so infra_tools didn't own the directory
   or its permissions and the layout diverged from everything else.

## Decisions

- **Persistence: managed shared dir** (not `/opt`). A service's durable data
  lives under the same root as Rails state, keyed per component so multiple
  services in one repo don't collide:

  ```
  <base>/.infra_tools_shared/<app_name>/<component>/        # {{shared_dir}}
  <base>/.infra_tools_shared/<app_name>/<component>/data/   # {{data_dir}}
  ```

  infra_tools creates these, chowns them to the service user, and (because it is
  outside the release dir) they survive the release being replaced on each
  deploy. Unlike Rails — which *symlinks* the shared state into the release
  because Rails assumes in-tree paths — a service references the directory
  **directly** via its config/env (`DB_PATH={{data_dir}}/…`), so no symlink is
  needed. We do **not** move Rails/node to `/opt`; consolidating onto
  `.infra_tools_shared` keeps all persistence in one place, co-located with the
  per-app backups already written there.

- **Users: one dedicated `--system` user per service component.** Each service
  runs as its own `nologin` user that owns only its `shared_dir`/`data_dir`. The
  release tree stays owned by the deploy user and world-readable so nginx can
  serve static files and the service can read its binary. Static components need
  no user at all.

## Service identity & naming

Identity is derived from the **release dir name** (`app_name`, e.g.
`bluehexagons_com`, already unique per domain/path) **and** the component name
(unique within a manifest), so it is unique across repos on one host. This also
fixes a latent collision in the first manifest cut, where `app-<component>`
alone clashed if two repos shared a component name.

| Thing            | Value                                             |
|------------------|---------------------------------------------------|
| systemd unit     | `app-<app_name>-<component>.service`               |
| service user     | same string, capped to a valid 31-char Linux name (a deterministic short hash suffix is used when truncated) |
| `{{shared_dir}}` | `<base>/.infra_tools_shared/<app_name>/<component>`|
| `{{data_dir}}`   | `<shared_dir>/data`                                |

The `app-*` prefix keeps these covered by `cleanup_all_infra_services`.

## Ownership / permission matrix

| Path                         | Owner               | Mode  | Why                                  |
|------------------------------|---------------------|-------|--------------------------------------|
| release dir (`/var/www/<app>`) | deploy user:group | 0755  | nginx reads static; service reads binary (world r-x) |
| `{{shared_dir}}` / `{{data_dir}}` | service user      | 0750  | only the service may read/write its data; not world-readable |
| operator secrets (`{{shared_dir}}/.env`) | service user | 0640 | `EnvironmentFile=`; readable by the service only |

A service therefore needs no write access anywhere in the release tree; its only
writable location is its own `data_dir`, which pairs naturally with
`ProtectSystem=strict` + `ReadWritePaths={{data_dir}}` in the unit.

## Template variables (additions)

`{{shared_dir}}` and `{{data_dir}}` join the existing set (see
`PROJECT_MANIFEST.md` → Templating). A unit/env can then be fully managed:

```ini
ExecStart={{binary}}
EnvironmentFile={{shared_dir}}/.env
ReadWritePaths={{data_dir}}
User={{web_user}}        # resolved to the dedicated per-service user
```

For a service component, `{{web_user}}`/`{{web_group}}` resolve to the service's
**dedicated** user (not the global deploy user), so a repo-supplied unit gets the
isolated identity automatically.

## Implementation (manifest path)

- `DeploymentOrchestrator._service_identity(app_name, component)` → `(unit_name,
  username)`; `_component_shared_dir` / `_component_data_dir`.
- `ensure_service_user(username)` — `useradd --system --no-create-home --shell
  /usr/sbin/nologin` (idempotent), mirroring `web/cicd_steps.py`.
- `_install_service_component` creates `shared_dir`/`data_dir`, ensures the user,
  chowns the data tree to it (0750), and builds the unit context with the
  dedicated user + `{{data_dir}}`/`{{shared_dir}}`.
- The release-tree chown to the deploy user is unchanged; only the (separate)
  data tree is service-owned.

## Future work (not done here)

- **Legacy path migration.** Give Rails/node deploys per-app dedicated users too,
  and reconcile the existing single-`rails`-user deployments (a one-time
  ownership migration). Deferred to avoid disrupting live single-user sites on a
  non-overhaul branch.
- **Backups under the service user.** The per-app backup dir
  (`.infra_tools_shared/<app>/backups`) currently follows the deploy user; align
  it with the per-service ownership when the legacy path moves.
