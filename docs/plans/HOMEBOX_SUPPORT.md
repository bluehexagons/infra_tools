# HomeBox service support

Status: initial native implementation delivered, 2026-09-07; automatic updates
and full VM qualification remain deferred.
Tracks [issue #99](https://github.com/bluehexagons/infra_tools/issues/99), whose
description links to the maintained `sysadminsmedia/homebox` project and has
no additional requirements or comments at the time of review.

This is the HomeBox-specific brief under the
[lightweight service project](LIGHTWEIGHT_SERVICE_CANDIDATES.md). It does not
change the remaining monitoring project's order or the roadmap's P0/P1 priorities.

## Implementation record

The user authorized implementation after the initial brief. Configuration,
native setup, private bootstrap, health, explicit upgrades, complete backup and
restore, and data-preserving disable are implemented. The live operator
contract is [HomeBox inventory](../HOMEBOX.md); the design sections below retain
the original scope and acceptance targets.

- `lib/homebox_config.py` owns validation; parser/config, controller and target
  validation, and the server plugin carry intent through setup and patch.
- `web/homebox_steps.py` owns verified staging, systemd/Nginx, private
  transient bootstrap, persistent secrets, locking, maintenance, migration
  rollback, explicit restore, and health. `lib/homebox_cli.py` provides remote
  operations. Web-panel links contain only public endpoint facts.
- Fresh setup pins v0.26.2; reruns retain the saved executable identity.
  Downgrades require full restore. Public HTTPS is checked through a local-only
  readiness route while normal ingress is blocked. Local/tunnel clients must
  be quiesced by the operator during maintenance.
- HomeBox intentionally supports amd64 only. The target rejects other release
  architectures before HomeBox setup mutations begin; upstream ARM64 assets
  are out of scope.
- Tests exercise configuration/cache/remote/patch round trips, conflicts,
  dry runs, release integrity, archive traversal, bootstrap policy, complete
  restore, damaged-state repair, idempotency, and failures before/after ingress.
- The actual amd64 v0.26.2 release passed native startup, closed-registration
  rejection, group invitation, login, item creation, attachment upload, API-key
  access, password-reset URL generation, and stopped backup/full restore in
  temporary storage. Login, API keys, and attachment hashes survived restore.
  Generated ACME/HTTPS Nginx configurations passed `nginx -t` with temporary
  certificates and unprivileged fixture ports; the systemd unit passed
  `systemd-analyze verify` with a fixture
  executable. The full default suite passed 3,425 tests with one live test
  skipped. Full Debian VM restart/reboot, public TLS, and WebSocket browser behavior
  remain follow-up validation. ARM64 was deliberately removed from scope. Unit tests mock
  system mutations; no production service was installed during development.
- Scheduled updates, automatic retention, monitoring integration, and
  Cloudflare ingress remain outside this initial delivery.

## Recommended first scope

Support one HomeBox inventory instance per Debian server through the existing
server setup pipeline, following Gogs' service composition pattern:

- A verified native Linux amd64 binary, dedicated `homebox` system account,
  and hardened systemd service.
- SQLite and local attachment storage beneath `/var/lib/homebox`, with an
  optional validated absolute data path and required-mount guards.
- A loopback backend, with either SSH-tunnel access or a dedicated hostname
  behind managed Nginx and HTTPS. Reserve a stable backend port and reject
  conflicts with Gogs, the web panel, and other managed applications.
- Repeatable setup, protected first-user creation, health checks, complete
  backup/restore instructions, and explicit version upgrades.
- Automatic updates only in a later slice after migration recovery is tested.

Defer Docker/Compose, PostgreSQL, remote object storage, multiple instances,
subpath hosting, OIDC, SMTP provisioning, MQTT, printer integration, and
migration of existing unmanaged installations. Native installation is our
proposed fit; upstream supplies binaries but recommends Docker for production,
so native operation needs its own disposable-VM validation.

## Verified upstream baseline

The release API reported **v0.26.2** during this review. Use it as the research
baseline, not a promise that it will remain the selected version. Recheck the
release and security notes before implementation.

| Finding | Consequence |
| --- | --- |
| Linux x86_64 archives and `checksums.txt` are published | Use the x86_64 asset only, record its exact version and SHA-256, and reject non-amd64 machines before downloading |
| Native HTTP defaults to port 7745; host binding is configurable | Set `HBOX_WEB_HOST=127.0.0.1` explicitly and validate the port |
| Current SQLite and storage settings are `HBOX_DATABASE_SQLITE_PATH`, `HBOX_STORAGE_CONN_STRING`, and `HBOX_STORAGE_PREFIX_PATH` | Render explicit absolute paths; do not copy obsolete `HBOX_STORAGE_DATA` examples |
| Registration defaults to enabled | Bootstrap privately, then disable registration before enabling normal ingress |
| `HBOX_AUTH_API_KEY_PEPPER` is required, at least 32 bytes, and changing it invalidates API keys | Generate once, store protected, preserve on rerun, and include in recovery |
| Database setup runs pending migrations at startup | Restoring only the old executable is insufficient rollback |
| Proxy guidance includes forwarded headers and WebSocket events | Test HTTPS URL generation, proxy trust, upload limits, and `/api/v1/ws/events` |

Evidence: [release assets](https://github.com/sysadminsmedia/homebox/releases/tag/v0.26.2),
[native installation](https://github.com/sysadminsmedia/homebox/blob/v0.26.2/docs/src/content/docs/en/quick-start/install.mdx),
[configuration](https://github.com/sysadminsmedia/homebox/blob/v0.26.2/docs/src/content/docs/en/quick-start/configure/index.mdx),
[configuration source](https://github.com/sysadminsmedia/homebox/blob/v0.26.2/backend/internal/sys/config/conf.go),
[database startup](https://github.com/sysadminsmedia/homebox/blob/v0.26.2/backend/app/api/setup.go),
and [proxy documentation](https://github.com/sysadminsmedia/homebox/blob/v0.26.2/docs/src/content/docs/en/quick-start/configure/proxy.mdx).

## Operator interface

These command shapes are implemented:

```bash
# Private instance, reached through an SSH tunnel.
infra-tools setup server_lite inventory-host operator \
  --homebox :7745 /srv/homebox

# Hostname with managed HTTPS; PORT is the frontend port, as with Gogs.
infra-tools setup server_web inventory-host operator \
  --homebox inventory.example.com:443 /srv/homebox --ssl
```

Propose `--homebox DOMAIN[:PORT] [DATA_PATH]`, with domainless `:PORT` meaning
loopback-only access, default backend port 7745, and hostname frontend default
443. Reject plaintext hostname exposure. Keep backend allocation separate
from the frontend port so several HTTPS services can share Nginx.
Cloudflare ingress should follow the existing tunnel contract when added;
the first slice need only support loopback and Nginx/Let's Encrypt.

Add a validated `--homebox-version TAG` selector. Fresh setup resolves an
approved stable release to a concrete tag/digest; reruns retain the recorded
version unless an upgrade is explicitly selected. Persist non-secret setup
intent through saved configuration, remote arguments, and patch flows.

Propose `infra-tools homebox health HOST [--json]`, reporting service state,
version, listener, local readiness, configured frontend readiness, storage
capacity, and database integrity. Distinguish missing observations and an
incomplete bootstrap from healthy operation. Expose only non-secret service
links in the web panel; a loopback endpoint is not a remotely reachable link.

## Bootstrap and configuration ownership

Use root-owned releases under `/opt/homebox/releases/<tag>-<digest>` and a
managed current link. Keep configuration and the pepper in protected files
under `/etc/homebox`; the service may write only its data and required runtime
paths. Preserve the pepper across reruns and stop with an actionable error if
an existing installation loses it. Keep secrets out of argv, saved setup
commands, JSON status, logs, and support bundles.

The first spike must verify an upstream-supported way to create and detect
the initial local user and group. Prefer protected credential input and a
loopback registration API call while external ingress is withheld. Do not
assume HomeBox has Gogs' administrator CLI or account model, or write user
records directly into SQLite. If unattended creation is unsuitable, use a
documented SSH-tunnel onboarding step with an explicit incomplete-bootstrap
state. Neither path may expose open registration publicly during setup.

After bootstrap, set registration off and verify the effect on new users and
group invitations. Reruns must not recreate users or reset passwords. Confirm
password recovery without SMTP before declaring the native service supported.
Set production mode explicitly; disable demo/debug and analytics. Keep
application authentication enabled. Trust forwarded headers only behind the
managed loopback proxy and define which configuration keys infra-tools owns.

## Release activation and recovery

Validate the requested release, architecture, checksum, archive paths, free
space, filesystem, and configuration before interrupting an existing service.
Use private staging and immutable release directories. Reject traversal and
unsafe links in archives. Publisher checksums establish integrity relative to
that publisher; do not describe them as independent signature verification.

For an upgrade, block writes, stop HomeBox, and take a consistent recovery set
of SQLite, attachments, configuration, pepper, and release/state metadata.
Keep requests blocked until the new process and frontend pass readiness.
On migration/startup failure, stop the new process and restore the complete
pre-upgrade set with the previous release and managed configuration. If
recovery cannot complete, leave a clear failed state and preserve artifacts.
Do not automatically restore an old snapshot after reopening writes: that
would discard newly accepted inventory changes.

An initial stopped-service backup is simpler than coordinating an online
SQLite snapshot with attachment writes. Document the short outage and test
restoration to a clean instance, including login, API keys, and attachments.
The generic [`--backup`](../BACKUPS.md) is an rsync mirror, not an existing
application-consistent snapshot/restore facility. It may copy completed backup
artifacts off-host. Keep live SQLite on local storage and reject missing mounts
or unsafe overlap with other services and exported writable shares.

## Implementation map and delivery sequence

| Slice | Likely owning files | Completion boundary |
| --- | --- | --- |
| 0. Native lifecycle spike | Upstream tagged source and disposable VM notes | Verify amd64 binary layout/dependencies, readiness endpoint and expected response, account/group bootstrap, invitation policy, password recovery, and migration/restore behavior |
| 1. Configuration and planning | `lib/arg_parser.py`, `lib/config.py`, `lib/validation.py`, `lib/setup_common.py`, `plugins/server.py` | Parse, validate, serialize, reconstruct, patch, and dry-run the proposed options; reject unsupported system types before target mutation |
| 2. Initial setup | New `web/homebox_steps.py`; reuse `lib/release_management.py` and existing Nginx/TLS, machine capability, and state helpers | Install verified release, configure isolated service/storage, complete private bootstrap, and health-gate ingress and successful state |
| 3. Operations and recovery | New `lib/homebox_cli.py`, CLI registration, `common/web_panel_steps.py`, service-owned backup/upgrade helpers | Health text/JSON, panel facts, explicit upgrades, complete backup/restore, and documented disable/removal that preserves data |
| 4. Scheduled maintenance | HomeBox updater under `common/service_tools/`, plugin wiring and notification integration | Enable a timer only after recovery tests pass; use the same lock, version policy, activation, and rollback path as explicit upgrades |

Use the Gogs implementation as a reference, not a wholesale copy: its Git/SSH,
LFS, user bootstrap, firewall rules, and binary rollback assumptions are
application-specific. Reuse common helpers without creating a general app
registry or a second setup engine. Target mutations remain behind
`remote_setup.py` and plugin-selected steps. Use the capability helper matching
each package, service, or filesystem operation.

## Acceptance and validation

- Focused unit tests cover malformed specs/paths/versions, port conflicts,
  unsupported architectures/system types, config round trips and patching,
  dry-run with no mutation, and coexistence with Gogs and the web panel.
- Release tests reject missing/wrong checksums, unsafe archives, and invalid
  state without replacing a healthy installation.
- Setup tests cover preserved users/data/pepper on rerun, incomplete bootstrap,
  registration closure, missing mounts, failed systemd startup, and invalid
  Nginx configuration without a success marker or premature ingress.
- Upgrade tests inject migration/readiness failures and verify restoration of
  the old database, attachments, secrets, binary, unit, proxy, and state.
- All unit tests mock system calls and use temporary directories. Run focused
  suites and relevant wider checks following the contributor guide.
- Disposable Debian VM validation exercises native install on amd64,
  restart/reboot, TLS, login, item creation, attachment upload/download,
  WebSocket events, repeat setup, and backup/restore to a clean instance.
- Update CLI/reference docs and add `docs/HOMEBOX.md`; update backup,
  credential, web-panel, and maintenance docs as their behavior lands.

Remaining qualification should exercise amd64 on a disposable Debian VM before
enabling scheduled updates. The larger monitoring project can consume HomeBox
health facts later.
