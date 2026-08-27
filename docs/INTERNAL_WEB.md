# Internal HTTPS sites and live previews

`infra-web` publishes static builds and explicit loopback development servers
through the HTTPS gateway managed by infra_tools. The gateway reuses the VM's
certificate and saved access-source policy; do not bind development servers to
`0.0.0.0`, edit Nginx, or add UFW rules manually.

The gateway is installed by features that configure the internal web host,
including the T3 Code web interface and the Godot web bundle.
T3 Code installations also place the managed web-gateway skill in compatible
terminal agents, so the publishing workflow is discoverable without enabling
the Godot bundle.

## Publish a static site

For a Vite or similar JavaScript project with a `build` script:

```bash
cd ~/repos/my-site
infra-web publish site
```

The publisher derives the site name from `package.json`, installs dependencies
when `node_modules` is absent, runs the build, detects `dist`, `build`, `out`, or
`public`, and atomically activates the result. It never runs project build
commands as root. Published sites share the existing TCP 8443 HTTPS origin and
do not consume a dedicated listener or firewall rule:

```text
https://HOST:8443/sites/USERNAME/my-site/
```

Specify the name, project, or output when detection is not sufficient:

```bash
infra-web publish site docs --project ~/repos/product --output web/dist
infra-web publish site docs --project ~/repos/product --no-build --output dist
infra-web publish site docs --no-install
infra-web publish site docs --json
infra-web publish site docs --open
```

`--no-build` requires an existing output directory. `--no-install` skips the
automatic dependency installation but still runs the build. Static output must
contain `index.html`, remain inside the project, and contain no symbolic links
or special files.

Inspect and remove publications as the owning user:

```bash
infra-web site list
infra-web site url docs
infra-web site doctor docs
infra-web site remove docs --yes
```

A failed build or activation keeps the previous publication available.

## Start a managed live preview

Use a supervised preview when hot-module replacement, an API, or WebSockets are
required:

```bash
cd ~/repos/my-vite-project
sudo infra-web preview start my-project --project .
```

For Vite projects, infra-tools detects the `dev` or `preview` package script,
allocates a private loopback port, supplies strict `127.0.0.1` binding
arguments, starts a bounded systemd service as the requesting user, waits for
HTTP readiness, and then creates the managed HTTPS forward. The service is not
enabled at boot.

Override automatic Vite detection with an explicit argv command after `--`.
Use `{host}` and `{port}` placeholders without shell interpolation:

```bash
sudo infra-web preview start my-project --project . -- \
  ./serve-preview --host '{host}' --port '{port}'

sudo infra-web preview start my-game --project . --profile godot -- \
  ./preview-server --listen '{host}:{port}'
```

The command is stored in an owner-only launcher beneath a root-managed
directory and is executed with `User=` and `Group=` set to the requesting
account. It is not executed by the privileged gateway process. `--profile
godot` adds cross-origin isolation headers for threaded Godot previews.

Useful lifecycle commands are:

```bash
infra-web preview list
infra-web preview url my-project
infra-web preview logs my-project
infra-web doctor my-project
sudo infra-web preview stop my-project
sudo infra-web preview prune --yes
```

Use `--replace` to deliberately replace an existing same-named preview. A
startup, readiness, route, or state-write failure rolls back both the service
and route. `preview prune` removes stopped services and their routes; it does
not touch another user's previews.

## Forward an existing loopback service

Keep `forward` as the low-level path when another service manager already owns
the upstream process:

```bash
sudo infra-web forward add api-preview \
  --to 127.0.0.1:3000 \
  --wait 30 \
  --health /health

infra-web forward list
infra-web forward url api-preview
infra-web doctor api-preview
sudo infra-web forward remove api-preview
```

The forward list reports whether each upstream TCP port is ready. Use
`sudo infra-web forward prune --yes` only for unmanaged dead forwards; managed
preview services should be cleaned up through `preview prune`.

## Certificate trust

When the VM uses its local certificate authority, enroll the public CA
certificate once on each LAN client. The command prints the file, download URL,
and SHA-256 fingerprint:

```bash
infra-web ca
```

Do not disable TLS verification. `site doctor` and the general `doctor`
command verify the same trusted HTTPS endpoints that browsers should use. For
an authenticated forward, a `401` response with a `WWW-Authenticate` challenge
confirms that the protected endpoint is reachable; other error responses still
fail the check.

## Security and state

- Static builds and live commands run as the configured non-root owner.
- Live upstreams are limited to unprivileged loopback ports.
- Only Nginx's HTTPS listener receives a managed UFW rule.
- One explicitly named project is exposed at a time; ports are never discovered
  and exposed automatically.
- Generated Nginx, firewall, publication, preview, and systemd state is
  validated before mutation and scoped to its recorded owner.
- Preview units use systemd process, memory, privilege, device, kernel, and
  address-family limits.

Use `infra-web forward reconcile` after repairing managed state, and
`infra-web doctor NAME` to validate a reachable forwarded endpoint.
