# Generic VM Management, Agent Web Interfaces, and Lightweight Git Hosting

Status: implementation-ready project brief; individual delivery lanes remain
subject to the dependency gates below. Reviewed against `main` and upstream
T3 Code documentation on 2026-08-20.

This project sharpens infra-tools around the environments it is intended to
serve: small businesses running Debian systems on their own Proxmox hardware
or on manually created VPS instances. Proxmox is the only infrastructure
provider infra-tools will provision or manage in the first release. A VPS from
DigitalOcean or another host remains an ordinary SSH setup target created and
destroyed outside infra-tools.

The project has three related tracks:

1. move virtual-machine operations into a provider-neutral command surface,
   with a Proxmox implementation and additional practical Proxmox lifecycle
   operations;
2. make the existing minimal Gogs service a deliberate Git and Git LFS server
   for low-end systems, including explicit storage, health, and recovery
   contracts; and
3. let an agent VM run explicitly selected web interfaces, beginning with T3
   Code, behind a small and secure service, proxy, and access-policy contract.

The tracks share the same product constraints: prefer straightforward
open-source components, keep saved commands as the reusable declaration, and
avoid abstraction whose only purpose is a hypothetical provider or service.

## Product decisions

- A QEMU/KVM VM is the normal isolation boundary for agentic development and
  other disposable workloads. Docker and Dev Container orchestration are not
  part of this project.
- Proxmox remains the only managed virtualization provider. The command model
  should permit another provider later, but no generic cloud framework or
  DigitalOcean API integration will be built now.
- Existing, manually provisioned VPS instances continue through the normal
  `setup`, `patch`, host registry, SSH, and saved-command workflows. They do
  not appear as managed VMs unless a future provider explicitly owns them.
- Provider-neutral VM commands own guest lifecycle. Proxmox-specific commands
  own nodes, clusters, storage, placement, maintenance, and notifications.
- Gogs remains the current Git service because its single binary, SQLite
  support, and low resource needs fit the target hardware. Forgejo, Tangled,
  and other Git services are deferred until there is a concrete second
  implementation to inform a shared service contract.
- Gogs's built-in local Git LFS server is the supported LFS backend. This
  project does not introduce a separate LFS daemon or object-storage service.
- Gogs LFS object transfer is supported, but LFS file locking is not. LFS uses
  HTTP/HTTPS authentication even when ordinary Git uses an SSH remote; setup
  and documentation must not imply otherwise.
- The next release intentionally breaks compatibility with unreleased
  development commands, configuration shapes, and internal APIs. A redesign
  must update saved-command rendering, documentation, completions, callers,
  and tests in the same change, then remove the superseded path instead of
  carrying aliases, adapters, deprecated fields, or dual dispatch.
- Agent web interfaces are explicit selections. `--web-interface t3code`
  installs and runs T3 Code's headless service; it does not imply a general
  agent suite, a desktop AppImage, or every available provider CLI.
- Remove `t3code` from `--agent-tool` and retire the current AppImage installer.
  T3 Code is an interface that drives selected provider CLIs, not a provider
  agent itself. A future desktop package requires a separate explicit
  desktop-interface option and a concrete use case; it is not an alias for the
  web service.
- T3 Code is an acceptable first interface because its source is available
  under the MIT license. Each later interface still needs its own license,
  release, runtime, and update-path review before being added.
- Prefer small infra-tools modules for deterministic parsing, validation,
  rendering, state inspection, and health checks. Continue to use mature
  open-source components for security-sensitive or protocol-heavy work such
  as TLS, WebSocket proxying, process supervision, Git, and SQLite.

### Breaking-release boundary

Unreleased development interfaces are not migration inputs. The release
should document the new command equivalents, but it must not accept the old
Proxmox guest paths, old raw reconfiguration arguments, retired agent-suite
flags, duplicate shell commands, or stale setup fields. Internal
`container_*` APIs should be renamed or removed in the same changes that
update their callers.

Persisted records need an explicit schema version. If a development build
wrote an incompatible host or setup record, the new release should refuse to
mutate it and print the short re-registration or command-regeneration steps.
It must not silently reinterpret old fields, destroy the record, or retain a
permanent migration branch. Saved setup commands should be regenerated under
the new parser before upgrade.

Tests should assert that removed parsers, fields, functions, and shell
commands are absent. Migration notes are documentation, not a compatibility
layer.

## Current implementation baseline (2026-08-20)

### Setup and VPS targets

`infra-tools setup` already treats an existing Debian host as an SSH target.
That is the complete intended integration for a manually created VPS: the
operator creates the instance, networking, and provider firewall, then runs
the same setup command used for a physical host or an existing VM.

The setup flow can also create a Proxmox QEMU VM or LXC guest through
`--provision-on`. QEMU provisioning resolves and verifies a cloud image,
imports it into the selected storage, configures cloud-init, installs the SSH
key and QEMU guest agent, starts the guest, and hands the resulting address to
the normal remote setup engine. This composition should be retained rather
than creating a second target-configuration engine under the management CLI.

### Proxmox management

The current `infra-tools proxmox` tree combines two different concerns:

- host and cluster operations such as registration, discovery, audit,
  rolling update, placement, rebalance, storage cleanup, and notification
  configuration; and
- guest operations such as list, status, power control, health, configuration,
  resource modification, disk resize, snapshots, backups, migration, unlock,
  and destruction.

Most basic guest mutations already exist and should be moved rather than
rewritten. Important remaining gaps include a stable machine-readable guest
inventory, graceful reboot, clone, backup restore, clearer task waiting and
timeouts, and a consistent capability/error contract when an operation is not
available for a guest type or storage backend.

The implementation currently calls both QEMU VMs and LXC containers
"containers" in several internal names. That terminology should be corrected
as part of the CLI split. Generic VM operations must not silently claim that
all Proxmox LXC behavior is portable to a future VM provider.

### Gogs and Git LFS

`--gogs` currently installs a native Gogs release, Git, Git LFS, OpenSSH,
SQLite, a restricted `git` user, a hardened systemd unit, optional nginx/TLS
integration, an initial administrator, and a managed weekly release updater.
The selected data directory contains the database and repositories.

Gogs serves Git LFS through its own HTTP endpoints and supports a local LFS
object path. infra-tools currently relies on the upstream defaults because its
generated `app.ini` does not include an explicit `[lfs]` section. The public
documentation also does not identify the LFS object directory, include it in
the recovery inventory, check its capacity, or prove an LFS upload/download
after setup.

### Agent web interfaces

The current T3 Code installer downloads the desktop AppImage and creates a
desktop launcher. It does not install or supervise the separate headless CLI
service used by `t3 serve`, expose it through nginx, or manage remote pairing.
The new web-interface path replaces that installer; it does not retain the
desktop path as another mode or alias.

T3 Code's supported remote model already provides a headless server, one-time
owner pairing credentials, authenticated sessions, session revocation, and a
Linux systemd user service. Its server also serves the matching web client and
uses WebSockets. infra-tools should integrate those upstream contracts rather
than creating another T3 login database or maintaining a parallel T3 process
launcher.

## Goals

- Give operators one clear VM command tree whose common vocabulary does not
  expose Proxmox implementation names.
- Preserve one setup engine: provider provisioning creates the target, then
  normal SSH setup configures it.
- Keep Proxmox node and cluster administration explicit and make that command
  tree easier to navigate.
- Define the smallest provider contract supported by working Proxmox code,
  with explicit capability reporting instead of speculative methods.
- Add the missing Proxmox lifecycle operations most useful to a small
  operator: reboot, clone, backup restore, richer inventory, and dependable
  wait/verification behavior.
- Make destructive VM operations previewable, confirmable, and compatible
  with the transactional and recovery work already on the roadmap.
- Make Gogs's Git LFS storage layout explicit and suitable for a dedicated
  low-cost data disk.
- Include repositories, SQLite state, LFS objects, configuration secrets, and
  required metadata in one documented Gogs recovery contract.
- Ensure agent workspaces can explicitly install Git LFS before cloning normal
  repository declarations that use it.
- Let operators select one or more explicit agent web interfaces while keeping
  each backend bound to loopback and each public exposure explicit.
- Make a loopback service plus an SSH tunnel the safe zero-configuration web
  interface, with optional nginx hostname/TLS and CIDR filtering.
- Preserve each tool's native authentication and access-revocation model,
  while ensuring startup output and normal logs do not expose pairing secrets.
- Ensure web services see the same explicit agent binaries, credentials, and
  workspace paths as the configured login user without copying credentials
  into unit files.
- Keep text output concise while providing stable JSON for inventory, audit,
  and external control systems.

## Non-goals

- Provisioning, resizing, snapshotting, destroying, or billing DigitalOcean
  instances.
- Supporting AWS, Azure, Google Cloud, Kubernetes, Terraform, Pulumi, or a
  general cloud-provider plugin system.
- Managing arbitrary QEMU/libvirt hosts outside Proxmox in the first release.
- Replacing VM isolation with Docker, Podman, or Dev Containers.
- Treating a saved profile file as the source of truth; saved setup commands
  remain the reusable declaration.
- Adding Forgejo, Tangled, Gitea, GitLab, or a generic Git-service framework in
  this project.
- Adding an external Git LFS server, S3-compatible storage abstraction, or
  distributed object store.
- Emulating Git LFS file locking that Gogs does not implement.
- Making every Proxmox API or `qm` option available through a raw pass-through
  interface.
- Backing up disposable agent VMs as a substitute for committing or exporting
  unfinished Git work.
- Treating an agent web interface as a general-purpose application hosting
  platform, remote desktop, or automatically exposed development-server
  preview.
- Adding a generic username/password database, OAuth provider, identity proxy,
  Caddy, Traefik, or a container-based web-interface stack in the first slice.
- Installing or maintaining the T3 Code desktop AppImage in this release.

## Track A: provider-neutral VM commands

### Resource model

A managed VM reference consists of:

- a registered provider host, such as `ts1`;
- an opaque provider resource ID, such as Proxmox VMID `101`;
- the provider recorded by that host registration; and
- observed fields such as name, state, address, CPU, memory, disks, lock, and
  provider-specific kind.

The CLI accepts `HOST ID` as separate arguments. The provider adapter validates
the ID; the common parser must not assume every future provider uses an
integer. Provider hosts must declare their provider explicitly when persisted.
Incompatible records written by development builds should be rejected with a
command to re-register the Proxmox host under `provider = proxmox`; they should
not be interpreted through a permanent legacy branch.

Observed VM results should use typed records and a versioned JSON schema. The
common fields must remain small. Proxmox-only data may be included under a
clearly named provider section instead of expanding the common model whenever
`qm` exposes another field.

### Proposed VM command tree

Use positional `HOST` consistently and group subordinate resources under one
noun. Do not retain flat aliases for the development-era command names:

```text
infra-tools vm list HOST [--json]
infra-tools vm show HOST ID [--json]
infra-tools vm health HOST ID [--json]
infra-tools vm start HOST ID [--wait]
infra-tools vm shutdown HOST ID [--timeout SECONDS]
infra-tools vm stop HOST ID
infra-tools vm reboot HOST ID [--timeout SECONDS]
infra-tools vm pause HOST ID
infra-tools vm resume HOST ID
infra-tools vm modify HOST ID [--cores N] [--memory SIZE] [--balloon-min SIZE] [--dry-run]
infra-tools vm disk resize HOST ID VOLUME SIZE [--dry-run]
infra-tools vm snapshot list HOST ID [--json]
infra-tools vm snapshot create HOST ID NAME [--description TEXT] [--dry-run]
infra-tools vm snapshot rollback HOST ID NAME [--dry-run]
infra-tools vm snapshot delete HOST ID NAME [--dry-run]
infra-tools vm backup list HOST ID [--json]
infra-tools vm backup create HOST ID [options]
infra-tools vm backup restore HOST BACKUP --id ID [options]
infra-tools vm clone HOST ID --name NAME [options]
infra-tools vm migrate HOST ID --to DESTINATION [options]
infra-tools vm unlock HOST ID [--dry-run]
infra-tools vm destroy HOST ID [--force] [--yes]
```

Do not add `vm create` in the first release. Provisioning continues to compose
through `infra-tools setup ... --provision-on HOST`, which calls the provider
and then the one normal OS configuration engine. A later standalone creation
command would have to call those same provider functions and must not grow a
second setup path.

Every mutating command should offer `--dry-run` when a meaningful concrete
provider command can be rendered. Read-only commands should support `--json`
through one stable result format that includes `schema_version`. Unsupported
operations must fail before mutation and identify the missing provider,
guest-kind, storage, or guest-agent capability. Text and JSON output should
share one typed result; machine output must include a stable error code and,
for asynchronous Proxmox work, the provider task identifier and final task
state.

### Proxmox command boundary

After guest operations move, `infra-tools proxmox` remains the explicit
administrative namespace for the provider itself:

```text
infra-tools proxmox hosts list
infra-tools proxmox hosts add ...
infra-tools proxmox hosts remove ...
infra-tools proxmox hosts probe ...
infra-tools proxmox cluster discover ...
infra-tools proxmox cluster audit ...
infra-tools proxmox cluster update ...
infra-tools proxmox cluster top ...
infra-tools proxmox plan place ...
infra-tools proxmox plan rebalance ...
infra-tools proxmox storage list ...
infra-tools proxmox storage clean ...
infra-tools proxmox notifications ...
```

The exact grouping can be adjusted while implementing parser tests, but node
and cluster commands must not be duplicated under `vm`. Remove the interactive
Proxmox shell; saved commands and the normal parser are already the reusable
interface, and a second command language adds no required capability.

### QEMU and LXC boundary

QEMU VMs define the portable VM contract. Existing LXC provisioning and
lifecycle remain supported as intentional Proxmox features under an explicit
`proxmox lxc` subtree; they do not appear under generic `vm` commands. This
keeps future VM-provider semantics honest and matches the QEMU-first product
direction. Shared implementation helpers can still use a neutral internal
`Guest` name where `qm` and `pct` genuinely have the same contract.

### Provider implementation boundary

Do not begin with a comprehensive abstract base class. Extract typed provider
operations from existing Proxmox functions one command family at a time. The
initial registry needs only:

- provider identity and host resolution;
- read-only inventory and capability discovery;
- the lifecycle operations exposed by the common CLI; and
- a shared result/error vocabulary.

A future provider may implement only part of the command set. Capability
discovery and a clear unsupported result are preferable to no-op behavior or
provider-specific flags accepted by the common parser and ignored.

Provider credentials belong to the control system and must never be copied to
a managed guest. Proxmox continues to use its registered SSH identity. An
ordinary VPS setup target has no provider credential and cannot receive VM
lifecycle commands.

### Additional Proxmox capabilities

The following additions are in scope after the CLI split reuses all existing
behavior:

1. **Inventory and observation**: stable JSON, filters by name/status/type,
   guest-agent address discovery, current task/lock visibility, and consistent
   exit codes.
2. **Graceful lifecycle**: reboot, configurable shutdown/start waits, explicit
   immediate stop, and post-operation state verification.
3. **Clone**: full clone first, with validated target VMID, name, storage,
   address/cloud-init changes, and collision checks. Linked clones remain
   deferred until their template and storage dependencies are designed.
4. **Restore**: select one listed backup, validate target storage and VMID,
   restore without overwriting an existing guest, then optionally boot into an
   isolated network for verification.
5. **Snapshot safety**: report unsupported storage before creation, show the
   current snapshot state, and make rollback/delete confirmation proportional
   to data loss.
6. **Configuration**: retain typed CPU, memory, balloon, boot, and disk options.
   Remove the current arbitrary `--set KEY=VALUE` surface rather than
   presenting raw `qm`/`pct` arguments as provider-neutral.
7. **Recovery and unfinished work**: before a managed agent VM is destroyed or
   rebuilt, optionally inspect declared repositories for dirty work and local
   commits not present on a remote. Archiving patches or Git bundles is a later
   agent-workspace slice, not a reason to back up the entire VM.

An enabled workspace pre-destroy check is fail-closed: an unreachable guest,
unknown repository state, dirty files, or unpushed commits block destruction
unless the operator explicitly overrides the check. Confirmation output names
the provider host, VM ID, observed VM name, and any failed preflight; `--yes`
suppresses the prompt for automation but does not bypass capability or
workspace checks. `--force` is the explicit bypass and must be recorded in the
operation result.

Restore, rollback, clone, and destructive configuration changes must reuse the
roadmap's transaction markers and recovery conventions. They should not create
a VM-specific transaction framework.

## Track B: minimal Gogs and Git LFS hosting

### Configuration decisions

Keep the public service selection explicit as `--gogs` for now. Renaming it to
`--git-service gogs` before a second service exists would add a generic layer
without reducing implementation complexity. When Forgejo or Tangled becomes
real work, the common behavior should be extracted from two tested services
rather than predicted here.

The generated Gogs configuration should explicitly include:

```ini
[lfs]
STORAGE = local
OBJECTS_PATH = /selected/data/path/data/lfs-objects
OBJECTS_TEMP_PATH = /selected/data/path/data/tmp/lfs-objects
```

The object and temporary paths must be absolute after rendering, owned by the
`git` account, protected from symlink traversal, and created before Gogs
starts. The default remains inside the selected Gogs data path so one mounted
data disk contains repositories, SQLite, attachments, and LFS objects.

Do not add a separate LFS path in the first release. A later need to place
large objects on another mounted filesystem would require an explicit absolute
path and a backup/recovery inventory that treats it as a second data root.

### Exposure and release safety

Do not preserve the current hostless behavior that can bind Gogs to
`0.0.0.0` while UFW is absent. A hostname continues to mean nginx plus the
selected TLS or Cloudflare flow and requires `--ssl` or `--cloudflare`; Git and
web credentials must not cross a public plaintext connection. Without a
hostname, Gogs binds to loopback and setup prints an SSH tunnel command unless
one or more private sources are explicitly declared:

```text
--gogs :3000 /srv/gogs-data
--gogs-source 192.168.0.0/24
--gogs-source 10.0.0.0/8
```

`--gogs-source` is repeatable and valid only for hostless mode. Before Gogs
binds a non-loopback address, infra-tools must install and verify matching
IPv4/IPv6 UFW rules; if it cannot enforce them, setup fails without exposing
the service. Reconciliation installs replacement allow rules before removing
old ones. A source list is access control, not transport encryption; use
hostless HTTP only on a trusted or encrypted private network and prefer the SSH
tunnel for web login. Hostname mode remains intentionally public unless
another existing firewall policy restricts it.

A loopback-only Gogs service has no generally reachable HTTP endpoint for LFS
clients. Setup must label remote LFS transfer unavailable in that mode unless
the client uses a persistent SSH tunnel and matching per-repository LFS URL.
For routine LFS use, require either the HTTPS hostname mode or a validated
private source listener; successful Git-over-SSH alone is not an LFS readiness
check.

Release installation must verify the selected Gogs asset with an upstream
digest or signature before activation, then run the binary as the restricted
`git` user. Downloading over HTTPS and validating the release URL are not by
themselves artifact verification. A previously healthy release remains active
when verification, extraction, startup, or health checks fail.

### Capacity and low-end operation

The default service remains one Gogs process with SQLite and local files. Do
not add PostgreSQL, Redis, an object store, or container orchestration to the
baseline.

Add read-only checks for:

- service and SQLite health;
- repository and LFS directory ownership and writability;
- free bytes and inodes on every data filesystem;
- total repository, LFS object, attachment, and log usage;
- failed or stale Gogs update jobs; and
- nginx upload limits that would reject the documented LFS workload.

Capacity warnings should report facts and configurable thresholds; they must
not automatically delete repositories or LFS objects. Gogs remains the owner
of object reachability, so a generic filesystem cleanup must never prune the
LFS directory. When Cloudflare or another operator-managed edge sits in front
of Gogs, report that its account-specific body-size and timeout limits are
outside infra-tools' control; a small health upload does not prove that the
largest intended LFS object will pass that edge.

### Backup and restore contract

A recoverable Gogs instance includes:

- `custom/conf/app.ini` and the persisted secret needed to reproduce it;
- the SQLite database;
- all Git repositories and server-managed hooks;
- all completed Git LFS objects;
- attachments, avatars, and other selected data-root contents; and
- enough infra-tools state to identify the installed release and data paths.

For the low-end SQLite baseline, the first consistent backup workflow may use
a short planned service stop while the complete data roots are snapshotted or
archived. A live copy of the database, repositories, and LFS objects at
different points in time must not be presented as a verified backup. Incomplete
temporary LFS uploads should be discarded during restore rather than preserved
as durable data.

Restore is complete only after Gogs starts and an integration test can:

1. authenticate to a temporary or designated test repository;
2. clone normal Git content;
3. download an existing LFS object;
4. upload and retrieve a new test LFS object; and
5. remove the temporary repository or test branch without touching operator
   repositories.

The backup implementation and retention policy belong to the roadmap's shared
recovery project. This plan defines the Gogs data inventory and verification
contract that project must consume.

### Agent Git LFS clients

Keep the existing host-neutral `--repo` declaration and select the Git LFS
client once for the target user:

```text
--git-lfs
--repo https://git.example.com/team/assets.git
```

Do not add a second `--repo-lfs` URL list. Git LFS installation and user
initialization are VM-level concerns, while `.gitattributes` and repository
content determine whether each clone uses LFS. This avoids parallel repository
APIs and lets public or authenticated repositories on any Git host retain the
same preparation path. A server using Gogs LFS does not imply that every agent
VM or repository needs the client, so the option remains explicit.

When selected, setup installs the Git LFS client before all repository clones,
runs non-repository user initialization, and uses the normal target-side HTTPS
clone. A clone fails clearly when required LFS objects cannot be downloaded.
An existing repository remains protected from reset or overwrite;
diagnostics may report missing LFS objects without fetching them implicitly.
For an SSH Git remote, diagnostics must still verify the separate HTTPS LFS
credential path and explain that successful SSH authentication alone is not
enough for object transfer.

## Track C: agent web interfaces

### Declaration and command shape

Web interfaces belong to normal target setup so the same feature works on a
new Proxmox VM, an existing VM, or a manually created VPS. The initial setup
shape is:

```text
--web-interface t3code
--web-interface-host t3code agent.example.com
--web-interface-port t3code 443
--web-interface-source t3code 192.168.0.0/24
--web-interface-source t3code 10.0.0.0/8
```

`--web-interface` is repeatable across distinct tools. Each companion option
takes `TOOL VALUE`, matching existing multi-value setup options and avoiding a
new `key=value` mini-language. A tool may run once per target Unix user; the
first release does not add custom instance IDs or multiple T3 Code services.
Duplicate tools, options for undeclared tools, shared hostnames, and actual
listen-address/port/hostname collisions fail during local validation.
Distinct hostnames may share nginx port 443.

The port option is the client-facing nginx port, not the tool's upstream port.
Each interface adapter owns one fixed loopback default and validates that an
unmanaged process is not already using it; T3 Code uses its upstream default
of 3773. Do not add an automatic port allocator or allocation profile for the
first release. The saved setup command remains the declaration; generated
units, nginx sites, and observed service state are derived data.

The following exposure modes keep a bare declaration useful and safe:

1. With only `--web-interface t3code`, run the service on loopback and print a
   reusable SSH tunnel command. Do not install or open nginx for that
   interface.
2. With `--web-interface-host`, proxy the loopback service through the existing
   nginx flow. Require `--ssl` or `--cloudflare`; port 443 is the default. DNS
   and certificate prerequisites must be checked before replacing an active
   site. Direct private access remains the recommended deployment, so setup
   warns before exposing a hostname without a source restriction.
3. With one or more `--web-interface-source` values but no hostname, allow an
   explicitly private HTTP listener through nginx. Require an explicit public
   port that differs from the tool's loopback port. This is for a routed
   private network such as an encrypted VPN, or a deliberately trusted LAN;
   CIDR filtering does not encrypt pairing credentials. The setup result must
   also explain that an HTTPS hosted client cannot connect to a plain
   HTTP/WebSocket backend because of browser mixed-content policy.
4. Reject a non-loopback listener that has neither a hostname/TLS policy nor a
   CIDR restriction. The tool backend itself always remains on loopback so the
   nginx and firewall policy cannot be bypassed.

Source values accept IPv4 or IPv6 addresses and CIDRs through the existing
network validators. nginx should enforce `allow` rules against the actual
socket peer followed by `deny all`; UFW should expose the matching listener
only to the same sources. A tunnel or CDN changes the observed peer address,
so source filtering must not claim to preserve the browser's original IP
unless a separately validated trusted-proxy configuration exists. Reject
source filtering with a Cloudflare tunnel in the first release unless its
client-IP restoration and trusted-proxy chain are explicitly supported and
tested.

### Authentication and secret handling

The first implementation uses native tool authentication when it exists. T3
Code's pairing token is exchanged for a session, and `t3 auth` can issue new
pairing credentials, inspect sessions, and revoke access. A source allowlist
is optional defense in depth for T3 Code and mandatory for any future
interface that has no suitable native authentication. A loopback-only SSH
tunnel is also sufficient network authentication for such a tool.

Do not add raw passwords to setup arguments, saved commands, process
environments, or systemd unit files. Generic nginx Basic Auth is deferred: T3
Code does not need a second login prompt, while safely designing password
input, hashing, rotation, recovery, and WebSocket behavior would be more work
than the first use case warrants. If a later unauthenticated tool needs public
access, add a username plus interactive or file-based secret input; never a
literal command-line password.

Pairing URLs and tokens must be treated as credentials. Normal setup output,
saved commands, dry runs, generated nginx files, and service logs must not
contain them. Before using the upstream background service, verify whether its
startup path writes an initial token to its private log. If it does,
infra-tools must use the upstream on-demand `t3 auth` flow or a redacting
launcher so ordinary journald and setup logs never capture the token. An
explicit access-issuance command may return a new token once to an interactive
operator, but JSON status and diagnostics must always redact it.

The web interface is effectively a remote shell with access to agent and Git
credentials owned by the setup user. Documentation and setup output should
describe it at that privilege level, not as a harmless dashboard. Session
revocation, pairing expiration, and interface removal must be documented next
to the initial connection flow.

Use the existing remote agent-management shape for lifecycle and access
operations:

```text
infra-tools agent web status HOST USER [--tool t3code] [--json]
infra-tools agent web pair HOST USER --tool t3code
infra-tools agent web sessions HOST USER --tool t3code [--json]
infra-tools agent web revoke HOST USER --tool t3code ACCESS_ID
```

`pair` invokes the tool's supported access-issuance command on the target and
prints the credential once to an interactive terminal; it has no JSON mode and
refuses a non-TTY output stream. `status` and `sessions` expose only non-secret
identifiers and metadata. `revoke` accepts a listed pairing or session
identifier and verifies that it is no longer usable. These commands reuse the
normal managed SSH identity and redaction path rather than creating an HTTP
administration endpoint.

### T3 Code runtime and service integration

`--web-interface t3code` replaces the retired `--agent-tool t3code` AppImage
path and installs the supported headless `t3` CLI and the Node
runtime version it requires. Reuse a compatible explicitly selected Node
runtime; otherwise install only the minimum runtime owned by the T3 interface.
Git is a required T3 dependency and is installed if absent. The selection does
not require a separate `--node` flag, install the desktop AppImage, or install
GitHub CLI or provider CLIs that were not explicitly selected with
`--agent-tool`. Setup should report when no supported provider CLI is selected,
but it may still install the interface so credentials or providers can be
added later.

Use T3 Code's supported `service install`, `service update`, and `service
uninstall` lifecycle instead of maintaining a second version-switching and
database-migration implementation. infra-tools may install a managed systemd
drop-in for validated bind options, working directory, absolute executable
paths, resource limits, and the explicit login-user `PATH`. The service must
run as that user with lingering enabled and must read provider credentials from
that user's normal protected configuration locations. Credentials must not be
copied into nginx or service configuration. Resolve and invoke the real CLI
package entry point when installing or updating the service; do not depend on
a wrapper symlink being a valid package root.

Setup ordering is explicit: install selected provider CLIs, stage their
credentials and non-secret configuration, prepare repositories and Git LFS,
then install or update the T3 runtime, register declared repository paths with
T3 Code, and start the service. Expose nginx/firewall only after
service-context health succeeds. A credential rotation should restart T3 only
when the affected provider requires it and should verify the provider again
after restart.

T3 Code's current remote GUI cannot add projects, so setup must idempotently
register each successfully prepared `--repo` path through the supported `t3
project` command before reporting the interface ready. It must not register an
unvalidated path, change an existing repository, or make repository discovery
depend on the service working directory. Documentation should give the same
target-side command for adding a project later and note when upstream UI
support makes that step unnecessary.

The service environment needs deliberate binary discovery because a systemd
user service is not a login shell. Include system and user-local binary paths
and verify every selected provider CLI from the running service context, not
only from an interactive SSH shell. The selected workspace root must also be
explicit so project discovery does not depend on systemd's default working
directory.

nginx integration must preserve the original host and scheme, forward
WebSocket upgrade headers, use bounded but agent-appropriate request and idle
timeouts and upload limits, and avoid response buffering where it breaks
streaming. It must use the repository's shared managed-site ownership,
staging, full-config validation, activation, and rollback primitives rather
than adding another nginx writer. Generated sites and units are activated only
after validation and are restored if the service or proxy health check fails.

### Reconciliation, health, and low-end operation

Each interface definition owns one service instance, nginx site when present,
firewall rules, and a small observed-state record. Re-running the same command
is idempotent. Removing an interface from a saved command should show the
stale managed resources and require the normal reconciliation/removal
confirmation rather than leaving an unknown listener or deleting tool data
silently.

Observed state has an explicit schema version and records ownership, tool,
Unix user, installed version, fixed backend port, generated artifact paths,
exposure mode, and last health result. It contains no credential or copied
configuration data. Reconciliation removes only artifacts carrying the same
infra-tools ownership marker; a same-named unmanaged unit or nginx site is a
hard error. Dry run lists every resource that would be created, replaced,
retained, or removed.

T3 Code conversations, sessions, and settings are user data even on a
disposable VM. Interface removal should stop exposure while retaining that
state by default and report its path and sensitivity. Full VM recreation may
discard it; an operator who chooses to preserve it needs an encrypted backup
that is consistent with the installed T3 version. This plan adds the data to
the recovery inventory but leaves archive transport and retention to the
shared recovery project.

Health output should report, without secrets:

- tool, target Unix user, installed version, and service state;
- loopback endpoint and externally advertised URL, if any;
- nginx configuration and certificate state;
- active access mode: SSH-only, native authentication, and/or source CIDRs;
- provider CLI discovery from the service environment;
- declared-project registration and reachability;
- HTTP readiness and a WebSocket/authentication-aware probe; and
- restart count, recent update result, memory use, and disk use for retained
  interface state.

Every interface must have independent resource accounting. Conservative
systemd memory and process limits should fit low-end VMs but remain
configurable; an out-of-memory restart must be visible instead of becoming an
unexplained reconnect loop. Updates must not interrupt active agent work
silently. T3 Code's version-skew and service update workflow should remain the
owner of its staged update and rollback behavior.

### Browser automation and application previews

An agent web interface is separate from the existing optional Playwright
browser-automation capability. The former lets a person reach an agent UI;
the latter lets an agent launch a local browser and inspect a site. Selecting
T3 Code should not silently install browser binaries, and selecting browser
automation should not expose T3 Code.

It is also separate from remotely previewing a development server started by
an agent. T3 Code's served web client does not currently proxy an arbitrary
project-local preview port. Exposing every discovered development port would
bypass the interface access boundary and create SSRF, cookie, origin,
WebSocket, and cleanup problems. A later preview-gateway project can proxy one
explicit loopback target under the same authenticated origin, or setup can
print an explicit SSH tunnel for a selected preview port. It is not part of
the first web-interface slice.

### Dependency policy

Use this decision test whenever implementation proposes another package:

1. Keep mature software when it owns a security-sensitive protocol, complex
   lifecycle, or compatibility surface. nginx remains the TLS/WebSocket proxy,
   systemd remains the supervisor, and T3 Code remains the owner of its
   authentication, database migration, and version rollback.
2. Implement small deterministic behavior in infra-tools when Python's
   standard library and existing modules are sufficient. This includes
   web-option parsing, tool/host/port/CIDR validation, nginx rendering, state
   observation, health polling, redaction, and saved-command serialization.
3. Do not add a general proxy, supervisor, template engine, secrets daemon,
   container runtime, or `htpasswd` package for one narrow feature.
4. Record why a new runtime dependency is necessary, install it only when its
   owning explicit feature is selected, and pin or verify downloaded artifacts
   using the repository's existing supply-chain rules.

## Delivery sequencing and dependency gates

The three tracks are delivery lanes, not one six-step critical path. T3 Code
and Gogs work does not wait for Proxmox clone/restore, and read-only VM CLI
work does not wait for backup transport. Each slice must leave one coherent
public command surface; no release should contain both old and new aliases.

The shared roadmap imposes two gates:

1. Parser, validation, pure rendering, read-only observation, and removal of
   dead development APIs may proceed immediately. Any destructive VM mutation
   or multi-file service/firewall reconciliation must use the durable operation
   markers and staged activation contract from
   [transactional execution](TRANSACTIONAL_EXECUTION.md).
2. VM restore and claims of recoverable Gogs or T3 state depend on the shared
   recovery project choosing an archive/storage mechanism. Data inventory,
   consistency rules, and restore smoke tests can land before that backend.

### Lane A1: VM terminology and read-only commands

- Add provider and schema-version fields to registered infrastructure hosts;
  reject incompatible development records without mutating them and document
  the short Proxmox re-registration flow.
- Introduce neutral VM reference, observation, capability, result, and error
  types with stable text/JSON rendering.
- Move list, show, health, snapshot list, and backup list to the nested `vm`
  command shape.
- Rename internal `container_*` symbols where they apply to both or only to
  QEMU VMs; leave true LXC concepts explicit under `proxmox lxc`.
- Reorganize Proxmox host/cluster commands, remove the interactive shell and
  old guest paths, and update docs, completions, callers, and tests together.

### Lane A2: existing VM mutations

- Move lifecycle, typed modification, disk resize, snapshots, migration,
  unlock, backup creation, and destroy through the provider boundary.
- Add reboot, bounded wait/timeout handling, capability preflights, provider
  task IDs, durable operation results, and post-operation verification.
- Remove arbitrary `--set KEY=VALUE` reconfiguration and expose only validated
  typed options.
- Preserve dry runs and confirmations, and require the shared staged-operation
  contract before destructive commands land.

### Lane A3: Proxmox clone and restore

- Implement full clone with explicit storage, cloud-init/network handling, and
  collision checks; keep linked clones deferred.
- Implement backup restore without overwriting an existing guest and with an
  optional isolated verification boot.
- Reuse shared durable operation and recovery records, then add live tests for
  directory/qcow2 and block-backed storage where behavior differs.

### Lane B1: explicit and safe Gogs LFS operation

- Verify release artifacts before activation and preserve the prior release on
  failure.
- Render and validate `[lfs]` paths, create the owned directories, and add
  Gogs/LFS capacity and health observations.
- Replace unsafe hostless exposure with loopback-by-default behavior and
  validated `--gogs-source` firewall rules.
- Add explicit `--git-lfs` agent-client setup before normal `--repo` clones.

### Lane B2: Gogs recovery contract

- Document complete data placement and add repositories, SQLite, attachments,
  secrets, and LFS objects to the recovery inventory.
- Implement the consistency boundary selected by the shared recovery project.
- Add an authenticated end-to-end backup/restore smoke test for ordinary Git
  and Git LFS data.

### Lane C1: loopback T3 Code service

- Add repeatable tool declarations and scoped `TOOL VALUE` options with
  validation and saved-command rendering.
- Remove T3 Code from the agent-tool registry and replace the AppImage installer
  with the verified headless CLI/runtime path and only its required
  dependencies.
- Integrate the supported user service with explicit HOME, PATH, workspace,
  fixed loopback port, provider discovery, and credential ordering.
- Register prepared `--repo` paths through T3 Code's supported project command
  and verify they are visible to the remote client.
- Add schema-versioned observed state, SSH-tunnel output, secret-free health,
  and `agent web` pairing/session/revocation commands.
- Do not complete this slice until startup and service logs pass pairing-token
  redaction tests.

### Lane C2: controlled network exposure

- Reuse shared nginx ownership and staged reconciliation for hostname/TLS and
  private CIDR modes, synchronized UFW rules, and rollback.
- Add HTTP, WebSocket, host/origin, upload, timeout, native-authentication, and
  no-direct-bypass health checks.
- Add update/removal reconciliation, retained-state reporting, resource limits,
  and low-end VM measurements.
- Validate T3 Code through an SSH tunnel, direct private CIDR access, and nginx
  HTTPS, including session revocation.

### Release integration

- Publish breaking-release notes and regenerated command examples.
- Document manually provisioned VPS setup, QEMU versus LXC boundaries, Gogs
  recovery, T3 exposure/pairing/revocation, and external DNS/firewall actions.
- Run the complete live Proxmox, low-end Gogs/LFS, and disposable T3 Code
  scenarios without affecting unrelated guests, repositories, or interfaces.
- Update the planning index and roadmap as each independently useful lane
  lands.

## Validation requirements

- Parser, rendering, and dispatch tests cover the positional-host and nested
  disk/snapshot/backup command shapes and prove old paths are absent.
- Provider tests use mocked SSH/system commands and verify capability failures
  occur before mutation.
- JSON fixtures prove stable field names and explicit provider data.
- Destructive-command tests cover dry run, confirmation refusal, timeout,
  partial provider failure, and post-operation verification failure.
- Restore and clone tests cover VMID/name collisions, unsupported storage,
  address conflicts, failed task completion, and cleanup of partial guests.
- Gogs tests use temporary directories and mock system calls; they verify LFS
  path rendering, permissions, symlink refusal, release-digest failure, nginx
  limits, safe hostless defaults, source-rule replacement, and backup
  inventory.
- Git LFS client tests prove installation and user initialization precede
  every normal repository clone without changing `--repo` URL handling.
- Web-interface parser tests cover repeated distinct tools, duplicate-tool
  rejection, scoped `TOOL VALUE` options, normalized IPv4/IPv6 sources,
  hostname and port collisions, undeclared tools, TLS requirements, fixed
  backend-port conflicts, unsupported Cloudflare/source combinations, and
  stable saved-command ordering.
- Parser and registry tests prove `--agent-tool t3code` and the AppImage
  installer are absent rather than retained as aliases.
- Unit tests render systemd and nginx configuration in temporary directories,
  mock all service/firewall calls, and prove that backends bind only to
  loopback, WebSocket headers are present, source rules end in `deny all`, and
  activation rolls back on a failed health check.
- Redaction tests seed recognizable pairing URLs, tokens, and agent credentials
  and prove none appear in setup plans, dry runs, generated configuration,
  status JSON, or normal service logs.
- Pairing-command tests require a TTY, omit JSON mode, display one issued
  credential once, and prove status/session/revocation output remains redacted.
- A live T3 Code test installs a selected provider CLI, discovers it from the
  running user service, opens a declared project, pairs a browser, reconnects
  with the session, revokes it, verifies rejection, and confirms an unrelated
  nginx site and systemd service remain active.
- A live Gogs test on modest Debian hardware pushes, clones, and restores both
  ordinary Git data and LFS objects over HTTPS, then proves an SSH Git remote
  still uses the configured HTTPS credential for LFS transfer.
- A live Proxmox test covers QEMU lifecycle, clone, snapshot rollback, backup,
  restore, and destruction without affecting an unrelated guest.
- No test talks to DigitalOcean or another cloud provider.

## Acceptance criteria

- An operator can manage a Proxmox QEMU VM entirely through `infra-tools vm`
  without using Proxmox-specific command names for common lifecycle actions.
- Proxmox node, cluster, storage, placement, maintenance, and notification
  commands remain available under a clearly organized provider namespace.
- The host registry determines the provider; an ordinary VPS target is not
  mistaken for a managed VM.
- Existing one-command Proxmox provisioning plus setup still uses the normal
  setup engine and emits a reusable saved command.
- VM list/show/health/snapshot/backup output has stable JSON and useful text.
- Reboot, full clone, and backup restore work with capability preflights,
  collision protection, waits, and result verification.
- Gogs runs on the SQLite/local-files baseline from a verified release artifact
  with an explicit local LFS object path.
- A configured Gogs service can accept and return LFS objects through its
  normal HTTPS URL without a separate LFS server.
- Documentation states that Gogs does not support LFS file locking and that
  SSH Git remotes still require HTTPS credentials for LFS object transfer.
- Gogs capacity output distinguishes repository, LFS, attachment, and log
  usage and never deletes reachable data.
- The documented backup inventory and restore smoke test cover Git repositories
  and LFS objects together.
- Hostless Gogs is loopback-only by default and cannot bind externally unless
  validated source firewall rules are active.
- Gogs health distinguishes local service readiness from a client-reachable
  LFS endpoint and does not mark loopback-only SSH Git as remote-LFS ready.
- Agent workspace setup can install Git LFS once and prepare normal `--repo`
  declarations without adding a parallel repository API or general
  development-tool suite.
- A bare `--web-interface t3code` creates a boot-persistent loopback service
  and reports a working SSH tunnel without opening a firewall port.
- T3 Code is selected only as a web interface; it is absent from
  `--agent-tool`, and no desktop AppImage is installed.
- Web-interface declarations are repeatable across distinct registered tools;
  duplicate T3 Code declarations are rejected, and each declared tool uses a
  stable non-conflicting loopback endpoint.
- A T3 Code hostname is served through nginx with valid HTTPS, WebSocket
  operation, native pairing/session authentication, optional CIDR filtering,
  and no direct upstream bypass.
- A private non-hostname interface requires an explicit client-facing port and
  source list, and setup refuses exposure when nginx or UFW cannot enforce the
  policy.
- T3 Code discovers only the explicitly installed provider CLIs from its
  service context and uses the setup user's existing protected credentials.
- Every successfully prepared `--repo` path is visible in the remote T3 Code
  client without requiring a second SSH setup session.
- An operator can issue one pairing credential, list non-secret sessions, and
  revoke access through managed SSH without opening an administration API.
- No pairing credential, session secret, or agent credential appears in saved
  commands, generated unit/proxy files, dry runs, status JSON, or ordinary
  logs.
- Removing or updating one interface preserves unrelated interfaces, reports
  retained state, and leaves no stale public listener.
- No DigitalOcean provisioning or management dependency is introduced.

## Cross-cutting gaps to close during implementation

The following are implementation gates rather than reasons to broaden the
first release:

1. **Exact T3 artifact and service contract**: the current AppImage path is not
   the headless CLI. Pin and verify the official CLI/runtime path, test its
   background-service and `t3 project` behavior, and confirm that update and
   database rollback work before enabling managed headless installation.
2. **Secret-bearing startup output**: prove whether the upstream service emits
   its owner pairing token to a private file or journal. Do not ship automatic
   startup until setup, status, and service logs pass the redaction tests.
3. **Service environment**: verify provider binary paths, credential homes,
   Git configuration, workspace ownership, and non-login `PATH` from inside
   the running service. An interactive-shell check is insufficient.
4. **Public-edge prerequisites**: DNS, certificate issuance, router/NAT rules,
   and VPS-provider firewalls may live outside infra-tools. Preflight what can
   be observed and print the exact remaining operator action without claiming
   the endpoint is ready prematurely.
5. **HTTP trust boundary**: test allowed host and origin behavior, forwarded
   scheme/host values, WebSocket authentication, request limits, and
   connection throttling. Never trust client-supplied forwarding headers from
   an untrusted proxy.
6. **Resource and update policy**: measure idle and active T3 Code operation on
   the intended 4 GB and smaller VMs, set conservative restart/resource
   defaults, and make updates wait for or explicitly interrupt active work.
7. **State and removal**: inventory T3 conversations, settings, sessions,
   logs, and installed versions; distinguish retained user data from generated
   service/proxy state and include the former in encrypted recovery guidance.
8. **Preview expectations**: keep agent UI access, Playwright automation, and
   development-server preview as three explicit capabilities. Do not expose
   arbitrary agent-started ports as a shortcut.
9. **Open-source and supply-chain review**: T3 Code itself is MIT-licensed;
   record transitive runtime/package licenses, release source, digest or
   signature behavior, download paths, and update ownership for T3 Code and
   Gogs before enabling unattended installation.

The shared recovery project still needs to choose the first backup archive and
storage mechanism. This plan defines the Gogs and T3 data consistency,
sensitivity, and verification contracts that mechanism must consume.

## Related implementation and plans

- `lib/proxmox_cli.py`
- `lib/proxmox_manage.py`
- `lib/proxmox_vm.py`
- `lib/proxmox_backup.py`
- `lib/proxmox_hosts.py`
- `lib/arg_parser.py`
- `lib/config.py`
- `lib/agent_cli.py`
- `lib/validation.py`
- `web/gogs_steps.py`
- `web/service_tools/deploy_admin.py`
- `common/agent_steps.py`
- `plugins/common.py`
- `lib/nginx_config.py`
- `docs/GOGS.md`
- [Agent VM workspaces and credentials](AGENT_VM_WORKSPACES.md)
- [Proxmox setup and maintenance audit](PROXMOX_MAINTENANCE_AUDIT_2026-08-09.md)
- [Transactional execution and reconciliation](TRANSACTIONAL_EXECUTION.md)
- [Project roadmap](ROADMAP.md)
- [T3 Code remote access](https://github.com/pingdotgg/t3code/blob/main/docs/user/remote-access.md)
- [T3 Code background service](https://github.com/pingdotgg/t3code/blob/main/docs/user/background-service.md)
- [T3 Code installation and provider discovery](https://github.com/pingdotgg/t3code/blob/main/docs/user/install.md)
- [T3 Code update lifecycle](https://github.com/pingdotgg/t3code/blob/main/docs/user/updating.md)
- [T3 Code MIT license](https://github.com/pingdotgg/t3code/blob/main/LICENSE)
- [T3 Code remote preview gateway gap](https://github.com/pingdotgg/t3code/issues/5101)
- [Gogs Git LFS documentation](https://gogs.io/advancing/git-lfs)
- [Proxmox VE Administration Guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf)
