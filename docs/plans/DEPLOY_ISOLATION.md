# Deploy Isolation: per-service users & managed persistence

> **Status:** Implemented for the **manifest** (`infra.json`) deploy path and
> the legacy Rails detection path. Release trees use a deployment owner; runtime
> services use dedicated `--system` users.

## Problem

Two gaps in the deploy path, surfaced while wiring `infra.json`:

1. **No user isolation.** The older `setup ... --deploy` path ran deployed
   Rails apps under one shared `rails` user (`remote_setup.py`,
   `deploy/deploy_steps.py`). A compromise in any one app could read/write every
   other app's files. infra_tools now uses the `web-deploy` owner for release trees
   and per-app runtime users for Rails (`rails-<app>`).

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

- **Users: dedicated `--system` runtime users.** Each manifest service runs as
  its own `nologin` user that owns only its `shared_dir`/`data_dir`. Legacy Rails
  services run as `rails-<app>` users that own only their persistent Rails state.
  The release tree stays owned by the `web-deploy` user and world-readable so nginx can
  serve static files and services can read their code/binaries. Static components
  need no runtime user at all.

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

Legacy Rails services keep the existing `rails-<app_name>.service` unit naming,
but the unit's `User=`/`Group=` are `rails-<app_name>` (capped with a
deterministic hash suffix when the Linux username would be too long).

## Ownership / permission matrix

| Path                         | Owner               | Mode  | Why                                  |
|------------------------------|---------------------|-------|--------------------------------------|
| release dir (`/var/www/<app>`) | `web-deploy:web-deploy` | 0755  | nginx reads static; service reads binary (world r-x) |
| `{{shared_dir}}` / `{{data_dir}}` | service user      | 0750  | only the service may read/write its data; not world-readable |
| operator secrets (`{{shared_dir}}/.env`) | service user | 0640 | `EnvironmentFile=`; readable by the service only |
| Rails private persistent state (`db`, `storage`, `log`, `tmp`, `backups`) | `rails-<app>` | 0750 dirs / 0640 files | Rails writes private state without exposing it to other app users |
| Rails public persistent state (`public/uploads`, `public/system`) | `rails-<app>` | 0755 dirs / 0644 files | nginx can serve public files through release symlinks |

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
**dedicated** user (not the release-tree owner), so a repo-supplied unit gets the
isolated identity automatically.

## Implementation (manifest path)

- `DeploymentOrchestrator._service_identity(app_name, component)` → `(unit_name,
  username)`; `_component_shared_dir` / `_component_data_dir`.
- `ensure_service_user(username)` — `useradd --system --no-create-home --shell
  /usr/sbin/nologin` (idempotent), mirroring `web/cicd_steps.py`.
- `_install_service_component` creates `shared_dir`/`data_dir`, ensures the user,
  chowns the data tree to it (0750), and builds the unit context with the
  dedicated user + `{{data_dir}}`/`{{shared_dir}}`.
- The release-tree chown to `web-deploy` is unchanged; only the (separate)
  data tree is service-owned.

## Implementation (legacy Rails path)

- `deploy_repository()` ensures a locked-down `web-deploy` owner instead of a
  framework-named user.
- `DeploymentOrchestrator` owns release/static trees as `web-deploy:web-deploy`.
- Rails runtime identity is derived from the release dir: `rails-<app_name>`
  with the same 31-character cap/hash strategy used for manifest users.
- Rails writable paths (`db`, `storage`, `public/uploads`, `public/system`,
  `log`, `tmp`) live under `.infra_tools_shared/<app>` and are symlinked into
  the release, then chowned to the Rails runtime user.
- Skipped deployments recreate a missing service and also replace an existing
  service whose `User=` still points at the old shared `rails` account.

## Future work (not done here)

- **Existing-host cleanup.** Code paths now recreate services with per-app
  users, but hosts may still have an unused legacy `rails` account after all
  deployments have been migrated.
- **Legacy Node runtime.** Legacy Node deploys are still served as static build
  output in the normal deployment path. The manual service helper uses
  `node-<app>` if it has to create a Node service.
