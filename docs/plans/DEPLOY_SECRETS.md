# Deploy Secrets & Optional Components — Plan

> **Status:** Planned, not yet implemented. Extends the manifest deploy path
> (`PROJECT_MANIFEST.md`, `DEPLOY_ISOLATION.md`) so the CLI can provision a
> service's env/secrets file instead of the operator hand-dropping it on the
> server, and so an optional backend is deployed only when its secret is present.

## Motivation

Two gaps remain after isolation:

1. **Secrets are hand-placed.** The operator must manually drop `.env` into the
   managed `{{shared_dir}}` on the server. We want the CLI to provision it.
2. **No conditional backend.** bluehexagons must deploy **with or without** the
   backend: no backend secrets → static-only site (no API service, no shop UI);
   backend secrets present → full site + API. The presence of a secret is the
   gate, and the static build must adapt.

## Secret source: workspace store (+ flag sugar)

Reuse the established workspace-credential pattern (`lib/credentials.py`):
operator-side secrets stored locally, referenced by name, **never inline in
argv** (argv is visible via `ps`).

- **Store:** a new secrets store in the workspace (sibling of the credential
  store), `0600`, JSON, keyed by `(app, component)` where `app` is the deploy
  spec's safe name (`create_safe_directory_name(domain, path)`). Values are the
  full env-file blob (opaque text).
- **CLI subcommand** `infra_tools secrets`:
  - `secrets set <deploy-spec> <component> --file <path>` (or `--stdin`) — store.
  - `secrets list <deploy-spec>` — names only, never values.
  - `secrets rm <deploy-spec> <component>`.
  - `secrets push <deploy-spec> <component> [--target HOST]` — provision/rotate
    onto the server without a full redeploy.
- **Deploy sugar:** `--deploy-env <component>=<path>` reads a local file at
  deploy time and provisions it (one-shot, no stored copy). Equivalent plumbing.

## Transport & placement (security)

- Read the secret **content** locally; stream it to the server **over SSH stdin**
  (e.g. `ssh … 'umask 077; cat > "$dst"'`) — never scp through world-readable
  `/tmp` (the nginx-config push uses `/tmp`; that is unacceptable for secrets).
- Destination is the managed path `{{shared_dir}}/.env`. After write: `chown` to
  the per-service user, `chmod 0640`; the parent `{{shared_dir}}` stays `0750`.
- Never echo or log secret contents; redact in all output and errors.
- The local store file is `0600` (enforced like `_ensure_secure_credentials_file`).

## Optional, secret-gated components

A service component may be marked optional; its deployment is gated on the
presence of a secret for `(app, component)`:

```jsonc
{ "name": "shop-api", "type": "service", "optional": true, ... }
```

- **Secret present** → push it to `{{shared_dir}}/.env`, deploy the service (user,
  data dir, unit, nginx reverse-proxy), poll health.
- **Secret absent** → **skip** the component entirely: no service, user, data dir,
  or nginx block. Its descriptor is omitted from the nginx grouping.
- A non-optional service with no secret is an error (fail fast) — it clearly
  needs one. A service with no `env_file` declared isn't gated at all.

## Build coupling: conditional env

The static build must vary on whether the optional backend ended up enabled. A
component declares extra **build env** that infra_tools adds only when a named
component is enabled — infra_tools owns the gating decision; the repo keeps one
build command. infra_tools is **agnostic to the variable name**; the repo chooses
it.

```jsonc
{ "name": "site", "type": "static",
  "build": "npm ci && npm run build",
  "env_when": { "shop-api": { "<REPO_CHOSEN_FLAG>": "1" } } }
```

- `shop-api` enabled → the `site` build runs with `<REPO_CHOSEN_FLAG>=1` merged
  into its `env`.
- `shop-api` skipped → plain build (static-only).

`env_when` keys must name components declared in the same manifest (validated,
fail fast); values are a string→string env map like `env`. (The current
bluehexagons flag is `VITE_SHOP`; renaming it to something less shop-specific is
a separate repo-side decision and out of scope here — infra_tools does not care
what it is called.)

## Deploy flow integration

1. Load manifest. For each service component, resolve whether it is **enabled**:
   `optional` → enabled iff a secret exists for `(app, component)` (in the store,
   or supplied via `--deploy-env`); non-optional → always enabled.
2. Compute the **enabled set** of component names.
3. Build each component, merging `env_when[c]` for every enabled `c` into the
   build env. (Skipped components contribute nothing.)
4. For each enabled service: provision its secret (stdin→`{{shared_dir}}/.env`,
   chown/chmod), then install the unit and poll health (as today).
5. Emit nginx descriptors only for enabled components.

This keeps gating in infra_tools and leaves the repo declarative.

## Schema additions (manifest version stays 1, additive)

| Field      | Where               | Notes                                                      |
|------------|---------------------|------------------------------------------------------------|
| `optional` | service component   | bool, default `false`. Gates deploy on secret presence.    |
| `env_when` | any component       | object: `{ component_name: { ENV: "value" } }`. Build env added when the named component is enabled. Keys must reference declared components. |

Unknown-field rejection still applies; both are validated in
`lib/project_manifest.py`.

## Example: bluehexagons, both ways

```bash
# Static-only (no backend): no secret stored -> shop-api skipped, plain build.
infra_tools setup server_web HOST --deploy bluehexagons.com GIT_URL

# Full: store the backend secret once, then deploy.
infra_tools secrets set bluehexagons.com shop-api --file ./shop.env
infra_tools setup server_web HOST --deploy bluehexagons.com GIT_URL
#   -> shop-api enabled: secret pushed to the managed .env, API deployed,
#      site built with the backend-UI flag set.

# Rotate secrets later without a redeploy:
infra_tools secrets push bluehexagons.com shop-api --target HOST
```

## Phasing

1. **Store + subcommand + transport:** secrets store module, `secrets` CLI,
   SSH-stdin push to the managed path with correct ownership/perms; unit tests
   (store round-trip, redaction, path computation) + a mocked push.
2. **Optional gating + `env_when`:** manifest schema + validation; orchestrator
   enable-set + build-env merge + skip logic; tests.
3. **bluehexagons:** mark `shop-api` optional, add `site.env_when`, document the
   two deploy modes; (optionally rename the build flag).

## Security summary

- Secret values never on the command line; only file paths or store references.
- Encrypted SSH transport; no world-readable staging; `0640` file owned by the
  isolated per-service user under a `0750` dir.
- Local store `0600`; contents never logged.
- A repo with no secret deploys exactly the minimal static site — the optional
  backend cannot be half-deployed.
