# CI/CD Manifest Reuse — Plan (future project)

> **Status:** Planned, not started. Split out of `PROJECT_MANIFEST.md` phase 3.
> The `infra.json` manifest is implemented and used by the `setup ... --deploy`
> path (build + serve locally on the target). This document captures what it
> would take for the **webhook CI/CD** path to consume the same manifest, so the
> two deploy paths share one source of truth.

## Motivation

Today there are two deploy paths with separate configuration:

- **`setup ... --deploy`** (`deploy/deploy_steps.py` → `DeploymentOrchestrator`):
  builds and serves on the target host. **Already manifest-aware** — reads
  `infra.json`, builds each component, installs services, generates per-domain
  nginx.
- **Webhook CI/CD** (`web/service_tools/cicd_executor.py`): a push triggers a
  build in a CI *workspace*, then `_deploy_to_remote` rsyncs the built artifact
  to a remote app server and pushes an nginx config. Build/serve behavior comes
  from server-side `repo_config['scripts']` in `/etc/infra_tools/cicd/…`, **not**
  the manifest.

The goal is to let the CI/CD path read `infra.json` too, so a repo describes its
build/serve contract once and both paths honor it.

## Why this is a separate project (the gap)

`_deploy_to_remote` is built around a **single artifact → single remote path →
single domain** model:

- one `detect_project_type(workspace)` + `get_project_root` → one `serve_path`;
- one `push_artifact(serve_path, target, remote_path, …)` rsync;
- one `generate_merged_nginx_config(domain, [deployment])` for one domain.

The manifest is **multi-component / multi-domain** (e.g. a static apex site *and*
a reverse-proxied API subdomain). It also has **service** components that need a
systemd unit installed and started on the remote host — something the rsync
path does not do today (it only pushes files and reloads nginx; service start is
left to an optional server-side `scripts.deploy`).

Mapping the manifest onto the remote-push path therefore is not a small shim; it
needs real design (below).

## Open questions / design options

1. **Where does the build happen for service components?**
   - *Build-in-CI, push artifact:* the Go binary is built in the CI workspace and
     rsynced. Requires the CI host's toolchain to match the target (CGO off /
     static binary makes this viable for Go; risky in general).
   - *Build-on-target:* push the source, run the manifest `build` on the target
     (closer to what `setup --deploy` already does). Simpler/consistent but moves
     compilation onto the app server.
   Decision needed; likely build-on-target to reuse `deploy_manifest` directly.

2. **Multiple components → multiple rsync targets + multiple nginx blocks.**
   Generalize `_deploy_to_remote` to iterate `manifest.components`, push each
   `output`/release as needed, and group nginx per domain (the descriptor →
   nginx grouping in `remote_setup.py` already exists and could be shared).

3. **Remote service install.** Run `create_managed_service` / `install_unit_file`
   (with `{{...}}` rendering) **on the remote host** — i.e. ship a small remote
   step rather than executing systemd locally. `remote_setup.py` already runs the
   full setup remotely; the cleanest route may be to have the CI/CD path invoke
   the existing manifest deploy on the target instead of the bespoke rsync path.

4. **Precedence with `repo_config['scripts']`.** If both a manifest and
   server-side scripts exist, the manifest should win (versioned with the code),
   with a deprecation path for scripts. Confirm before changing behavior.

## Sketch of the work

1. Factor the descriptor → per-domain nginx grouping out of `remote_setup.py`
   into a shared helper (also usable by CI/CD).
2. In `cicd_executor._deploy_to_remote`, `load_manifest(workspace)` before
   `detect_project_type`. If present, drive a remote manifest deploy (preferably
   by reusing `deploy_manifest` on the target via the existing remote-exec
   machinery) instead of the single-artifact rsync.
3. Health-poll each service from the remote side; surface failures in the CI log.
4. Tests mirroring `tests/test_manifest_deploy.py` but for the remote path
   (mock the remote-exec / rsync layer).

## Out of scope (for the first cut)

- Incremental/no-op redeploys (the local manifest path also rebuilds fully today).
- Honoring a repo-supplied unit *and* server-side scripts simultaneously.
- Non-Go service toolchains where build-in-CI cannot produce a target-compatible
  artifact.

## References

- `docs/plans/PROJECT_MANIFEST.md` — the manifest schema, templating, and the
  implemented `setup ... --deploy` path.
- `lib/deployment.py::DeploymentOrchestrator.deploy_manifest` — the local
  multi-component deploy to reuse.
- `web/service_tools/cicd_executor.py::_deploy_to_remote` — the path to adapt.
