# Developer Tool Role Model

## Observations

infra_tools currently treats Ruby, Node, Go, and Python tooling as optional
flags that can be mixed into workstation and server flows. That is flexible,
but it hides an important ownership distinction:

- Workstation developer tools are for the created login user. The user should
  be able to sign in over SSH or XRDP and run `node`, `npm`, `pnpm`, `ruby`,
  `bundle`, `uv`, and editor tooling without repairing permissions.
- Combined build+web servers need build tools for unattended deployment jobs
  and often for an operator account during development. The runtime and build
  owner should be explicit instead of inferred from whichever account ran setup.
- Split production build/web servers should keep build tools on the build
  server. The web server should receive only the runtime pieces required to run
  deployed services.

The immediate nvm failure fits this model. `install_node()` skips all work as
soon as `/home/<user>/.nvm` exists, so a root-owned or partially-owned nvm tree
is considered healthy. The nvm install and update commands also rely on
`runuser` defaults instead of pinning `HOME`, `USER`, and `LOGNAME` to the
target user. That makes root-owned caches plausible on fresh provisioning,
repair runs, and systemd-driven update paths.

## Driving Use Cases

### RDP Developer Workstation

Target user: `config.username`

The created user is the product. All user-scoped tools belong under that
user's home directory and must be installed by that user:

- nvm: `/home/<user>/.nvm`
- npm cache/config: `/home/<user>/.npm`, `/home/<user>/.config`, and related
  nvm cache paths
- uv: `/home/<user>/.local/bin/uv`
- shell initialization: `/home/<user>/.bashrc`

Setup may run as root, but root should only install apt packages, create users,
write system files, and chown explicitly-owned paths. It should not leave
language-manager caches owned by root.

### Combined Build+Web Server

Target users:

- operator/login user: `config.username`
- CI/CD user: `webhook`
- app/runtime users: deployment-specific service users, or the current legacy
  `rails` user path until that is replaced

This role currently installs user-scoped Node and uv for `config.username`, but
CI/CD workspaces run as `webhook`. That means the build server can still depend
on PATH and caches that are not owned by the actual build user. The project
should move toward a build-tool target owner, defaulting to the CI/CD user when
`--build-server` or `--cicd` is enabled.

### Split Build and Web Servers

Target users:

- build server: build tools owned by the build job user
- app server: deploy/runtime users only

App servers should not install nvm, Node build tools, Bundler, or uv unless a
specific deployed runtime needs them. Static deployments should only require
nginx and file ownership. Node and Rails services should use explicit runtime
contracts instead of inheriting the build server's toolchain layout.

## Proposed Direction

1. Add a shared user-tool execution helper that always runs commands as the
   target user with `HOME`, `USER`, and `LOGNAME` pinned to that user and a
   working directory inside the user's home.
2. Make user-scoped install steps idempotently repair ownership before returning
   "already installed".
3. Separate tool intent from tool implementation:
   - user tools: interactive login user's home
   - build tools: CI/CD/build user's home
   - runtime tools: deploy/runtime user's home or system package runtime
4. Replace broad `--node`, `--ruby`, and `--python` semantics with role-aware
   presets in a later pass. Existing flags can map to the correct role in this
   revision because backwards compatibility is not required.
5. Keep production app servers minimal. Build outputs should be copied from the
   build server; app servers should only install build tools when a runtime
   explicitly cannot run without them.

## First Implementation Pass

The first code pass should fix the known nvm ownership failure without blocking
the larger redesign:

- repair ownership of existing nvm, npm, cache, config, and local tool paths
  before checking whether Node or uv is already installed;
- run nvm installer, `nvm install`, `npm install -g`, and uv installer/update
  with explicit target-user environment;
- run the Node auto-update service with explicit `HOME`, `USER`, and `LOGNAME`
  so nvm cache behavior stays tied to the systemd `User=`;
- add focused tests for the command environment and ownership repair behavior.

## Open Follow-Up Work

- Add a `ToolOwner` or similar config concept for login, build, and runtime
  owners.
- Teach `--build-server` to install Node/uv/Ruby for the build job user when
  the server will build those project types.
- Make deploy manifests declare build-time and runtime requirements separately.
- Remove the legacy single `rails` user path and align Rails/node services with
  per-app users described in `docs/plans/DEPLOY_ISOLATION.md`.
