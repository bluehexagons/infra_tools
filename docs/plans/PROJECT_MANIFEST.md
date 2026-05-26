# Project Manifest (`infra.json`) — Design

> **Status:** Phase 1 implemented (`lib/project_manifest.py` loader + validation
> + `tests/test_project_manifest.py`); phases 2–3 still pending. This document
> specifies a repo-side manifest that lets a deployed repository describe *how*
> it should be built and served, instead of infra_tools guessing from file presence.

## Motivation

Today, deployment classifies a repo with `detect_project_type()` in
`lib/deploy_utils.py` purely by which files exist (`.ruby-version`/`Gemfile`
→ rails, `package.json` → node, `index.html` → static). Project-specific build
and serve instructions live **server-side** in `/etc/infra_tools/cicd/webhook_config.json`.

This breaks down for repositories that:

- contain **more than one deployable component** (e.g. a static frontend *and* a
  compiled backend service in the same repo);
- use a toolchain detection doesn't cover (e.g. **Go**, which has no project type today);
- want their build/serve contract **versioned with the code**, reviewable in PRs,
  rather than configured out-of-band on each server.

The driving example is the `bluehexagons` repo: a Vite static site **plus** a Go
API service (accounts + store) that must run as a systemd unit behind an nginx
reverse proxy on a subdomain.

## Overview

A repository MAY include an `infra.json` at its root. When present, the
`--deploy` / `DeploymentOrchestrator` path loads it and uses it as the source of
truth for build and serve behavior, **overriding** `detect_project_type()`. When
absent, behavior is unchanged — this is fully backward compatible.

```jsonc
// infra.json
{
  "version": 1,
  "components": [
    { "name": "site", "type": "static",
      "domain": "example.com",
      "build": "npm ci && npm run build",
      "output": "dist" },

    { "name": "api", "type": "service",
      "domain": "api.example.com", "reverse_proxy": true,
      "build": "server/deploy/build.sh",
      "binary": "server/app",
      "systemd_unit": "server/deploy/app.service",
      "env_file": "/opt/app/.env",
      "port": 8080, "health": "/api/health" }
  ]
}
```

Format is JSON to match the existing config ecosystem (`webhook_config.json`,
`deploy_targets.json`, `.deploy_metadata.json`), stay dependency-free, and work
on `requires-python >=3.10` (no `tomllib`).

## Schema (version 1)

Top level:

| Field        | Type   | Required | Notes                                            |
|--------------|--------|----------|--------------------------------------------------|
| `version`    | int    | yes      | Manifest schema version. Currently `1`.          |
| `components` | array  | yes      | One or more components, deployed in array order. |

### Common component fields

| Field    | Type            | Required | Notes                                                        |
|----------|-----------------|----------|--------------------------------------------------------------|
| `name`   | string          | yes      | Unique within the manifest; used for dirs and service names. Must match `[a-z0-9-]+`. |
| `type`   | string          | yes      | `static` or `service`.                                       |
| `domain` | string          | yes      | Host to serve at (validated by `lib/validation.py`).         |
| `path`   | string          | no       | Sub-path, default `/`.                                       |
| `build`  | string / array  | no       | Shell command(s) run at repo root before serve. Omit to skip.|
| `env`    | object          | no       | Build-time environment variables (strings).                  |

### `type: "static"`

| Field    | Type   | Required | Notes                                                       |
|----------|--------|----------|-------------------------------------------------------------|
| `output` | string | yes      | Directory (relative to repo root) of built files to serve. Must exist after `build`. Served by nginx; no reverse proxy. |

### `type: "service"`

| Field           | Type   | Required | Notes                                                                 |
|-----------------|--------|----------|-----------------------------------------------------------------------|
| `binary`        | string | one of   | Path (relative to repo root) to the built executable to install/run.  |
| `exec`          | string | binary/exec | Full command to run instead of a single binary.                    |
| `port`          | int    | yes      | Loopback port the service listens on (used for the nginx upstream).   |
| `systemd_unit`  | string | no       | Path to a unit file in the repo to install as a template. If omitted, infra_tools generates one (analogous to `create_rails_service`). |
| `env_file`      | string | no       | Absolute path on the server for systemd `EnvironmentFile=`. Secrets live here, **never** in the repo. |
| `reverse_proxy` | bool   | no       | Default `true`. nginx proxies `domain` → `127.0.0.1:port`.            |
| `health`        | string | no       | HTTP path polled after (re)start to confirm the service is up.        |
| `working_dir`   | string | no       | Server-side working directory; default the deployment release dir.    |

Validation rejects: unknown `version`, duplicate `name`s, unknown `type`,
missing required fields, `output` escaping the repo root, and `port` outside
`1024–65535`. Unknown fields are rejected (fail fast) to surface typos.

## Integration with the `--deploy` path

New module **`lib/project_manifest.py`**:

```python
from __future__ import annotations
from lib.types import JSONDict

MANIFEST_FILENAME = "infra.json"

def load_manifest(repo_path: str) -> Manifest | None:
    """Return the parsed, validated manifest, or None if absent."""

class Manifest:        # dataclass: version, components: list[Component]
class Component: ...   # dataclass with the fields above + helpers
```

`DeploymentOrchestrator` (in `lib/deployment.py`) changes:

1. In `deploy_from_archive` / the deploy entrypoint, call `load_manifest(dest_path)`
   **before** `detect_project_type()`.
2. If a manifest exists, iterate `components`:
   - **static** → run `build`, resolve `output`, point nginx at it
     (reuse `_get_frontend_serve_path` / static nginx generation).
   - **service** → run `build`, install the binary into the release dir, install
     or generate the systemd unit (generalize `create_rails_service` into a
     `create_service` in `lib/systemd_service.py`), wire `EnvironmentFile=` to
     `env_file`, assign/keep a port via `_get_assigned_port` / `_find_free_port`,
     generate an nginx reverse-proxy server block for `domain`, and poll `health`.
3. If no manifest exists, fall back to `detect_project_type()` exactly as today.

Per-component nginx server blocks are generated independently, so one repo can
serve a static apex site and a reverse-proxied API subdomain from a single deploy.

## Backward compatibility

- No `infra.json` → identical behavior to today.
- The manifest is **additive**: a single-component static or node repo can adopt
  it for explicitness, but is not required to.
- `webhook_config.json` scripts continue to work; a later phase MAY let the CI/CD
  executor consume the same manifest so the two paths share one source of truth.

## Phased implementation

1. **Foundation (done):** `lib/project_manifest.py` loader + dataclasses +
   strict validation; unit tests for parse/validate; this doc.
2. **Orchestrator wiring:** multi-component build in `DeploymentOrchestrator`;
   generalize service creation; per-component nginx generation; health polling.
3. **CI/CD reuse (optional):** executor reads the manifest instead of server-side
   script config.

## Testing

Following `AGENTS.md` / `python3 -m unittest discover -s tests`:

- `tests/test_project_manifest.py`: valid multi-component parse; rejects bad
  version, duplicate names, unknown type, missing required fields, `output`
  path escape, out-of-range port, unknown fields.
- Orchestrator tests (phase 2) use a temp repo with an `infra.json` and assert
  the right build/service/nginx steps run (mirroring `tests/test_deployment_backup.py`).

## Example: `bluehexagons`

```jsonc
{
  "version": 1,
  "components": [
    { "name": "site", "type": "static",
      "domain": "bluehexagons.com",
      "build": "npm ci && npm run build",
      "output": "dist" },

    { "name": "shop-api", "type": "service",
      "domain": "api.bluehexagons.com", "reverse_proxy": true,
      "build": "server/deploy/build.sh",
      "binary": "server/bx-server",
      "systemd_unit": "server/deploy/bx-server.service",
      "env_file": "/opt/bx-server/.env",
      "port": 8080, "health": "/api/health" }
  ]
}
```

The static build excludes the shop UI by default (`npm run build`); the API is a
single static Go binary managed by systemd and reverse-proxied on the `api.`
subdomain so session cookies stay same-site with the apex site.
