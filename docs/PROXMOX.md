# Proxmox workflows

infra-tools can register Proxmox hosts, cache their capabilities, provision
Debian VMs or unprivileged LXCs, and manage guest lifecycle operations.
[Machine types](MACHINE_TYPES.md) explains the guest capability differences.
Provider-specific host operations and advanced mutations remain under
`infra-tools proxmox ...`. Common guest observations, resource statistics,
power-state lifecycle, boot ordering, and confirmed QEMU VM destruction are
available through the provider-neutral `infra-tools vm ...` commands; see the
command reference for the stable JSON shape.

These workflows target Proxmox VE 9.2 and use its current `qm` and `pct`
interfaces. Bridge discovery identifies Linux bridge interfaces by type, so
explicitly named Proxmox SDN bridges are supported alongside conventional
`vmbr*` bridges.

## Quick setup: Proxmox host to coding VM

Install infra-tools on a trusted Linux orchestration machine first. The
Proxmox host does not need a checkout; setup uploads the installed source to
`/opt/infra_tools`.

```bash
wget --timeout=20 --tries=2 -O "$HOME/.infra_tools-install.sh" https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh
sh "$HOME/.infra_tools-install.sh"
rm -f "$HOME/.infra_tools-install.sh"
infra-tools channel
```

If the orchestration machine is itself a Proxmox VM, install and activate its
guest agent during local self-setup:

```bash
sudo infra-tools self-setup --qemu-guest-agent
```

The option installs `qemu-guest-agent` and runs
`systemctl enable --now qemu-guest-agent`. VMs provisioned by infra_tools
already receive the same package and service configuration through cloud-init.

Set up, register, and inspect the host:

```bash
infra-tools setup server_proxmox 10.0.0.10 root \
  --key ~/.ssh/proxmox_ed25519 \
  --name pve1

infra-tools proxmox probe pve1
infra-tools proxmox top pve1
infra-tools proxmox ls pve1
infra-tools vm list pve1 --json
```

Successful `server_proxmox` setup registers the host in the selected workspace;
`--name` supplies the registry name and defaults to the host address when omitted.
New host records explicitly store `schema_version: 1` and
`provider: proxmox`. Records produced by earlier development builds are not
silently reinterpreted. If loading the registry reports an unsupported schema
or missing provider, run `infra-tools proxmox remove NAME` using the name shown
in that record, then run the normal `server_proxmox` setup or
`infra-tools proxmox add` command again. Removal matches only the stored name
or address and can delete an incompatible record without interpreting it.
This is an intentional breaking-release boundary, not a credential or
guest-data migration.

The matching `.pub` file must sit beside the private key, and the Proxmox
`root` account must accept that key.

VM provisioning uses an SSH identity's `.pub` file for cloud-init. The key is
installed for both root and the configured guest setup username; the latter is
created with non-interactive sudo and is used for the route and remote setup
handoff. `--key` is optional: infra-tools first uses a matching key associated
with the registered Proxmox host, then the local `~/.ssh/id_ed25519`,
`id_ecdsa`, or `id_rsa` key.
If the Proxmox node key and guest key differ, pass `--provision-key` for the
node and `--key` for the guest. VM image downloads and cloud-init snippets are
placed through Proxmox storage APIs. By default, image staging prefers an
active file-based storage with `import` content and falls back to `iso` content;
use `--image-storage STORAGE` to choose the source storage explicitly. The
selected node must also have active `snippets` content for cloud-init data.
Custom VM image URLs must use HTTPS and include a matching 128-character
SHA-512 value with `--image-sha512`; the curated Debian catalog carries pinned
hashes automatically.

After a newly created VM or LXC begins accepting SSH, infra-tools scans its
ED25519 host key from the already authenticated Proxmox node and records it in
the workspace `known_hosts` file before the first direct guest login. A stale
entry for that guest address is replaced only in this new-provisioning path;
all following guest SSH still uses `StrictHostKeyChecking=yes`. Existing or
adopted guests are not trusted automatically. Verify them independently and
use `infra-tools ssh-key enroll HOST` when enrollment is required.

## Host-safety defaults

The `server_proxmox` flow uses Proxmox's native firewall rather than UFW and
does not create a generic `/swapfile`: Proxmox storage (especially ZFS) must
own its swap layout. It retains the host's permissive reverse-path filtering
because strict filtering can drop valid routed, NATed, or bridged guest
traffic.

By default, setup does not change Proxmox firewall state. Supplying
`--lan-access` or `--access-source` reconciles only infra-tools-commented
entries in Proxmox's standard cluster-wide `management` IP set, preserves
operator entries, then enables the cluster firewall after the replacement
sources exist. That standard set covers the Proxmox web GUI, SSH, VNC, and
SPICE, while Proxmox automatically includes the local cluster network. Because
enabling the firewall is cluster-wide, keep a recovery SSH or console session
open for the first rollout. `--no-access-source` and `--no-lan-access` remove
the corresponding saved policy and tool-owned set entries but deliberately do
not disable a firewall that may contain other policy.

Automatic host restarts and forced restart deadlines are disabled by default.
The setup reports pending restarts, but schedule any hypervisor reboot around
guest downtime (or opt in explicitly with `--auto-restart` or
`--auto-restart-force-days`).

The default setup installs these recurring host-maintenance timers:

- `security-monitor.timer` checks fail2ban and SSH events every 15 minutes and
  sends findings when notification targets are configured.
- `auto-update-apt.timer` applies non-removing distribution upgrades daily at
  06:00; Debian's competing APT timers are retired only after this replacement
  is verified active.
- `auto-restart-if-needed.timer` checks daily at 02:00 and after boot, but the
  default Proxmox policy records and reports a deferral instead of rebooting.
- `cleanup-maintenance.timer` removes unused APT packages and residual package
  configuration, audits `dpkg` consistency, cleans bounded caches, journals,
  old crash reports, and infra-tools-owned temporary artifacts, and ensures
  filesystem TRIM through the native timer or a cleanup fallback each Sunday.
  Post-cleanup checks cover block and inode pressure on distinct local storage
  mounts. The job does not prune backups, templates, ISOs, guest volumes, or
  directly modify `proxmox-boot-tool` kernel selections.

Inspect these jobs with the commands in [Recurring Maintenance](MAINTENANCE.md).
The timers do not currently validate Proxmox quorum, guest evacuation, storage
health, or backup recoverability. Run the Proxmox audit before planned
maintenance and verify backups through your normal retention and restore
process.

Create a Debian VM with XFCE, RDP, Firefox, and coding tools:

```bash
infra-tools setup workstation_dev 10.0.0.50 agent \
  --provision-on pve1 --base debian --name agent-dev-01 \
  --cores 4 --memory 8G --storage root 40G --image-storage local \
  --desktop xfce --rdp --browser firefox \
  --password "$RDP_PASSWORD" \
  --agent-tool gh --agent-tool codex --agent-config active --git-access read \
  --repo https://github.com/user/my_codebase.git \
  --node --go --python
```

For a newly provisioned QEMU VM, add named data disks and required guest
mounts in the same declaration:

```bash
infra-tools setup workstation_dev 10.0.0.51 agent \
  --provision-on pve1 --memory 8G --storage root 40G \
  --storage agent-data bulk-lvm 128G \
  --storage-mount agent-data /srv/agent-workspace ext4 \
  --agent-workspace /srv/agent-workspace \
  --agent-tool gh --agent-tool codex \
  --repo https://github.com/user/my_codebase.git
```

Each non-root `--storage NAME [POOL] AMOUNT` requires exactly one matching
`--storage-mount NAME PATH [ext4|xfs] [empty]`. When `POOL` is omitted, the
root-pool default is used. Provisioning checks that each selected pool is
active, accepts VM images, and reports enough aggregate free capacity. It then
attaches the disks as `scsi1`, `scsi2`, and so on with stable `it-NAME`
serials.

After SSH becomes ready, target setup identifies each disk by serial and
declared capacity, partitions and formats it only when it is confirmed blank,
and creates a required UUID-based systemd mount. Existing signatures, an
ambiguous device, a nonempty mount path, a wrong filesystem, or a failed mount
stops setup. The mount does not use `nofail`, and a marker on the mounted
filesystem prevents an empty root-disk directory from passing application
checks. Gogs and agent repository setup verify the mount before writing.
Observed mount state is stored root-only in
`/opt/infra_tools/state/vm-storage.json`; each mounted filesystem also carries
`.infra-tools-storage.json` for fail-closed verification.

This first slice is deliberately provisioning-only. It does not adopt an
existing disk, attach data storage to LXC, detach or resize a data disk,
migrate populated paths such as `/home`, or manage a manually attached VPS
volume. Supported empty mount targets are `/data` or paths below `/srv`,
`/var/lib`, `/opt`, and `/mnt`. `--image-storage` remains only the staging pool
for the VM image; it is not guest data storage. See the
[VM management and lightweight Git hosting plan](plans/VM_MANAGEMENT_AND_LIGHTWEIGHT_GIT_HOSTING.md)
for the deferred lifecycle work. Idempotent reruns are supported when the VM's
saved provisioning metadata matches the declaration; an existing unsaved VM
is not treated as permission to adopt disks.

Inspect a provisioned VM by its saved local `--name`:

```bash
infra-tools vm show agent-dev-01
infra-tools vm health agent-dev-01
```

The explicit provider host and VMID form remains available:

```bash
infra-tools proxmox ls pve1
infra-tools vm show pve1 100
infra-tools vm health pve1 100
```

Replace `100` with the VMID returned by `proxmox ls`.

`--rdp` requires `--password` for the non-root desktop account. Set
`RDP_PASSWORD` in a secure secret source rather than placing a literal in
shell history; the password is not persisted in saved setup state.

After a guest has been provisioned, a later `setup` invocation can retain
`--provision-on`. If the target has saved local setup metadata, infra-tools
reuses its recorded Proxmox details and skips contacting the Proxmox host
before updating the guest. Guest-shape options emitted by a saved reconstructed
command are also accepted when they match that metadata. Changing any of
`--machine`, `--bridge`, `--memory`, `--balloon-min`, `--storage`, `--cores`,
`--base`, `--image`, or `--image-storage` requests a provisioning check
instead. A target without saved provisioning metadata still requires
`--memory` and root `--storage` on its first run.

During a provisioning check, the configured IPv4 address is the stable guest
identity. If that VM already exists and the corrected declaration changes its
Proxmox name, infra-tools applies and verifies the rename before continuing
setup. A desired name already owned by a different VM is rejected rather than
creating an ambiguous duplicate. Repeating the saved `--name` and `--hostname`
values is an ordinary idempotent rerun and does not contact Proxmox. Changing
`--hostname`, or changing `--name` when it supplies the VM hostname, performs
the identity check. Use the explicit host and VMID forms to inspect or repair
provider-side drift and duplicates created by older releases.

## Graphical VM hardware baseline

Provisioned VMs that include a desktop or enable RDP are created with both a
VirtIO-GPU display and a serial socket. The VirtIO device supplies a usable
Proxmox noVNC recovery console; the serial socket remains available for boot
diagnostics. Server-only VMs retain `vga: serial0` to avoid an unused emulated
display. Existing desktop VMs created with a serial-only display can be shut
down and changed with `qm set VMID --vga virtio` on the Proxmox node.

The emulated display does **not** by itself accelerate an XRDP session.
xorgxrdp creates its own resizable X.Org display with the `xrdpdev` driver.
Infra-tools probes the guest for a supported, accessible DRM render node and
enables xorgxrdp glamor only when that probe succeeds; otherwise it retains the
software fallback. A VM is not granted `video` or `render` membership merely
because it has an emulated display.

The resulting Proxmox baseline is:

| Setting | infra-tools default | Rationale / alternative |
| --- | --- | --- |
| Display | VirtIO-GPU for desktop/RDP; serial-only for servers | VirtIO-GPU is a recovery console, not XRDP acceleration by itself. QXL/SPICE and `virtio-gl` do not replace the guest render-node probe. |
| Serial | `serial0: socket` | Retains low-level diagnostics alongside the graphical console. |
| CPU | `host` | Best performance on one node or a CPU-homogeneous cluster. Use a compatible `x86-64-v*` model when cross-generation live migration matters. |
| Machine/firmware | Proxmox defaults | Q35/OVMF are not required for an emulated display or XRDP; prefer them when PCIe GPU passthrough requires them. |
| Disk controller | VirtIO SCSI single with `iothread=1` on the root disk | Uses the per-disk I/O thread supported by the selected controller. Enable discard/SSD flags only when the backing storage policy supports them. |
| Network | VirtIO | Lowest-overhead normal Linux guest path. Multiqueue is normally unnecessary for interactive RDP traffic. |
| Guest agent | Enabled and installed | Supports clean lifecycle and guest inspection from Proxmox. |
| Entropy | VirtIO RNG backed by `/dev/urandom` | Gives Linux guests a reliable entropy source during early boot and key generation. |
| Memory | Fixed requested allocation with VirtIO balloon device enabled | Start around 8 GiB for the documented coding desktop and size for browsers, editors, builds, and agents. Use `--balloon-min SIZE` below `--memory` only when dynamic reclamation is intentional. |

These choices follow Proxmox's documented VirtIO network and VirtIO-SCSI
performance guidance and its warning that `host` CPU trades migration
portability for host feature exposure. Proxmox also documents that selecting a
serial display disables VGA output. Cloud-init installs the guest agent and
ensures Linux loads `virtio_balloon`. Keeping the balloon minimum equal to the
maximum preserves fixed allocation while allowing Proxmox to collect detailed
guest memory information. A lower minimum lets Proxmox reclaim memory under
host pressure, which can force guest swapping or out-of-memory handling; size
it for the VM's working set rather than treating it as free overcommit. Imported
images retain the native format selected by the destination storage backend,
and provisioning rejects a requested disk smaller than the source image. The
cloud-init snippet is detached from the VM before its temporary file is
removed, preventing a stale `cicustom` reference. See the current
[Proxmox VE administration guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf).

Physical GPU passthrough is a different profile. It needs host IOMMU/device
isolation, usually Q35/OVMF, and explicit guest drivers. If the guest exposes a
supported render node, the normal xorgxrdp probe can enable glamor; otherwise
the software fallback remains safe. Passthrough still requires separate
performance and compatibility testing and is not enabled by the default
provisioning profile.

## Provisioned web server VM

```bash
infra-tools setup server_web 10.0.0.50 admin \
  --provision-on pve1 --memory 4G --storage root 32G --cores 2 \
  --base debian --name web-01-vm --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

## Provisioned LXC

Use `--machine unprivileged` explicitly for an LXC and include template
storage:

```bash
infra-tools setup server_web 10.0.0.50 admin \
  --machine unprivileged --provision-on pve1 \
  --memory 4G --cores 2 --storage root 20G --storage template \
  --base debian --name web-01-lxc --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

`--storage` is repeatable. QEMU provisioning accepts one root disk using
`--storage root POOL AMOUNT` or the shorthand `--storage root AMOUNT`, plus
named data disks using `--storage NAME POOL AMOUNT` or
`--storage NAME AMOUNT`. Every named disk requires a matching
`--storage-mount`. LXC provisioning uses root storage and
`--storage template` for the saved/default template pool; named disks and
guest mount declarations are VM-only.
The guest bridge defaults to the bridge carrying the Proxmox host's default
route; use `--bridge NAME` when the host has multiple routed bridge networks.
The positional target is also the guest IPv4 address: a bare address assumes
`/24`, while `ADDRESS/PREFIX` selects another subnet without a duplicate
`--ip` option. Unless explicitly set, the IPv4 gateway is selected from the
chosen bridge's default route, then its own address, with the first usable
subnet address as a clearly reported fallback. DNS comes from the Proxmox
node, preferring bridge-specific resolvers; when the node exposes only a local
stub resolver, the inferred gateway is used.

## Guest lifecycle

### Resource pressure and boot recovery

Start troubleshooting a slow or memory-constrained host with the node summary,
then inspect the guests contributing to the load:

```bash
infra-tools proxmox top pve1
infra-tools vm stats fileserver
infra-tools vm stats build-agent --json
```

`vm stats` reads Proxmox's provider-side counters and does not require the QEMU
guest agent. It shows current CPU and memory use, disk allocation, cumulative
disk/network I/O, and uptime. Warnings highlight high CPU, memory, disk, or
reported swap use. Treat one sample as a clue: compare several samples before
resizing a VM, and check `proxmox top` to retain enough host memory for
Proxmox itself.

After a power outage, starting every VM together can overwhelm an older disk
or a small CPU. Inspect and configure typed boot settings with the saved local
VM name:

```bash
infra-tools vm autostart fileserver
infra-tools vm autostart fileserver \
  --enable --order 1 --start-delay 30 --shutdown-timeout 120
infra-tools vm autostart database \
  --enable --order 2 --start-delay 45 --shutdown-timeout 180
infra-tools vm autostart build-agent --disable
```

Lower order values start first and stop last. Put infrastructure dependencies
such as storage and DNS first, give slow services enough delay, and leave
disposable build or test VMs disabled. Unspecified order and delay values are
preserved when autostart is enabled again.

For a small host, a practical routine is:

1. Run `proxmox audit` and `proxmox top` before maintenance.
2. Use `vm stats` on the busiest guests before adding CPU or memory.
3. Keep host memory and disk headroom instead of allocating every available
   unit to guests.
4. Stagger essential autostart guests and disable nonessential ones.
5. Keep verified backups; a VM snapshot is convenient rollback state, not a
   substitute for a backup on separate storage.
6. Prefer `vm shutdown` to `vm stop`; immediate power-off can damage guest
   filesystems and application data.

### Power-state commands

For an infra-tools-provisioned VM, prefer its saved local name:

```bash
infra-tools vm status agent-dev-01
infra-tools vm start agent-dev-01
infra-tools vm pause agent-dev-01       # alias: suspend
infra-tools vm resume agent-dev-01
infra-tools vm shutdown agent-dev-01 --timeout 60
infra-tools vm stop agent-dev-01        # immediate; may cause data loss
infra-tools vm reboot agent-dev-01      # alias: restart
```

These commands also accept an explicit registered provider host and VMID, and
`--json` returns the provider-neutral result envelope. `shutdown` is the clean
power-off path; `stop` exits the guest immediately. Shutdown and reboot pass
an optional timeout to Proxmox and all lifecycle commands report the observed
state after the provider operation completes.

The provider-specific forms remain available for compatibility:

```bash
infra-tools proxmox status pve1 101
infra-tools proxmox start pve1 101
infra-tools proxmox stop pve1 101
infra-tools proxmox pause pve1 101
infra-tools proxmox resume pve1 101
infra-tools proxmox health pve1 101
```

For compatibility, the older `proxmox stop` command keeps its original
behavior: it requests a graceful shutdown unless `--force` is supplied. New
automation should use the explicit generic `vm shutdown` or `vm stop` form.

Show a summary for one or more nodes:

```bash
infra-tools proxmox top pve1 pve2
```

The summary includes node CPU, memory, storage, and guest counts. It is a
read-only health and capacity view; `probe` should be run first when a host's
storage or bridge data has not been cached.

Run a maintenance-safety audit before planned work:

```bash
infra-tools proxmox audit pve1 pve2
infra-tools proxmox audit pve1 --json
```

The audit checks core Proxmox services, quorum on clustered nodes, active tasks,
configured storage, at least 4 GiB of free root space, guest locks, running
guests, and whether a reboot is pending. Text output distinguishes general
health from reboot safety; JSON output is intended for automation. The command
is read-only and exits nonzero when a health check fails.

Proxmox SSH inspection commands reuse a short-lived OpenSSH control connection.
With an encrypted key, the first connection prompts for its passphrase and the
remaining checks reuse that authenticated connection. All Proxmox operations
allow that prompt when launched from a terminal; piped or parallel operations
require the key to be loaded into an SSH agent. See
[SSH authentication](SSH.md) for setup and troubleshooting.

Modify resources and configuration:

```bash
infra-tools proxmox modify pve1 101 --cores 4 --memory 8G
infra-tools proxmox reconfigure pve1 101 --set hostname=newbox
infra-tools proxmox reconfigure pve1 101 --set balloon=4096
infra-tools proxmox resize-disk pve1 101 rootfs 40G
```

For an existing VM, Proxmox stores `memory` and `balloon` in MiB. Keep
`balloon` no greater than `memory`; setting both to the same value disables
dynamic reclamation without removing the balloon device.

Snapshots and rollback:

```bash
infra-tools proxmox snapshots pve1 101
infra-tools proxmox snapshot pve1 101 pre-upgrade --description "before kernel update"
infra-tools proxmox rollback pve1 101 pre-upgrade
infra-tools proxmox delsnapshot pve1 101 pre-upgrade
```

`vm destroy` is permanent and asks for confirmation. For an infra-tools
provisioned VM, use its exact saved local name; infra-tools resolves the
registered provider host and VMID, then verifies the observed QEMU name and
configured IPv4 address before prompting:

```bash
infra-tools vm destroy agent-dev-01
infra-tools vm destroy agent-dev-01 --yes
infra-tools vm destroy pve1 101
```

The provider host/VMID form is useful for a QEMU VM without saved local setup
metadata. `--yes` skips only confirmation, while `--force` force-stops a
running VM before destruction. The command verifies that the VM is absent
afterward and retains the saved setup declaration for deliberate
reprovisioning; remove that declaration separately with
`infra-tools rm agent-dev-01` when appropriate. The legacy
`infra-tools proxmox destroy` path remains available during the broader guest
command migration.

## Placement, backups, and migration

The placement planner ranks registered nodes without changing them:

```bash
infra-tools proxmox plan place \
  --cores 4 --memory 8192 --disk 40 \
  --prefer-tag production --exclude pve3
infra-tools proxmox plan rebalance --limit 3
```

`plan rebalance` reports overloaded nodes and candidate destinations. It only
migrates when `--apply VMID` is supplied; use `--dry-run` to preview the
migration command and `--yes` to skip its confirmation prompt. `--to HOST`
overrides the top-ranked destination. Online migration and local-disk transfer
have the same storage and cluster prerequisites as the direct `migrate` command.

List and create immediate `vzdump` backups:

```bash
infra-tools proxmox backups pve1 101
infra-tools proxmox backup pve1 101 \
  --storage backup --mode snapshot --compress zstd --dry-run
```

The backup command defaults to the first backup-capable storage pool, snapshot
mode, and zstd compression. `suspend` and `stop` modes trade availability for
stronger consistency where the guest workload requires it. Always verify that
the selected storage has enough capacity and a retention policy outside
infra-tools.

Migrate a guest between registered cluster nodes:

```bash
infra-tools proxmox migrate pve1 101 pve2 --dry-run
infra-tools proxmox migrate pve1 101 pve2 \
  --online --with-local-disks
```

`--online` keeps a VM running and requires suitable shared or migrated storage.
`--with-local-disks` copies local disks to target-node storage. Use the dry run
first for production migrations.

## Orphaned volumes and stuck locks

List unreferenced guest volumes before deleting anything:

```bash
infra-tools proxmox clean-disks pve1 --dry-run
infra-tools proxmox clean-disks pve1 --delete
```

`clean-disks` is list-only by default. `--delete` requires typing `yes` unless
`--yes`/`-y` is supplied; treat it as destructive because an orphaned-volume
check cannot infer whether an external workflow still needs a volume.

After confirming that no backup, migration, or snapshot task is still active,
clear a stale Proxmox management lock:

```bash
infra-tools proxmox unlock pve1 101 --dry-run
infra-tools proxmox unlock pve1 101
```

The unlock operation only clears the guest lock; it does not repair a failed
underlying task or roll back partial storage changes.

## Cluster and notifications

```bash
infra-tools proxmox probe-cluster 10.0.0.10 \
  --key ~/.ssh/proxmox_ed25519 --tag prod
infra-tools proxmox hosts
infra-tools proxmox audit pve1 pve2 pve3
infra-tools proxmox rolling-update pve1 pve2 pve3
infra-tools proxmox notifications install-webhook \
  pve1 https://notify.example/hook --send-test
infra-tools proxmox notifications test-webhook pve1
infra-tools proxmox shell
```

`probe-cluster` discovers nodes from Proxmox's configured names and seeds the
host registry. `rolling-update` reuses saved setup commands and workspace
credentials. It audits every target before changing any node, repeats the audit
after each update and reboot, and advances only after verification. An automatic
reboot is refused while guests are running or locked; the remaining nodes are
then skipped so the operator can migrate or stop workloads deliberately.
`notifications install-webhook` configures Proxmox's native notification
matcher; repeat `--severity` to limit routing, and use `--dry-run` before
writing the endpoint. Treat webhook URLs as sensitive values.

## Network planning

Use the separate [Network inventory](NETWORKING.md) workflow to build a
workspace-scoped inventory and render a read-only Proxmox firewall plan before
applying any control-plane lockdown.

## Real-system smoke test

For a first rollout, validate one VM and one LXC compatibility path:

```bash
infra-tools proxmox hosts
infra-tools proxmox probe pve1

infra-tools setup workstation_dev 10.0.0.50 devuser \
  --provision-on pve1 --memory 8G --storage root 40G --cores 4 \
  --name dev-01-vm --rdp

infra-tools proxmox ls pve1
VMID=100  # replace with the VMID returned by `infra-tools proxmox ls`
infra-tools proxmox health pve1 "$VMID"
infra-tools proxmox snapshot pve1 "$VMID" pre-modify
infra-tools proxmox modify pve1 "$VMID" --cores 6 --memory 12G
infra-tools proxmox stop pve1 "$VMID"
infra-tools proxmox start pve1 "$VMID"

infra-tools setup server_lite 10.0.0.60 appuser \
  --machine unprivileged --provision-on pve1 \
  --memory 2G --storage root 10G --storage template
```

For the VM path, verify SSH and optional RDP access. For LXC, focus on basic
provisioning and guest management; advanced desktop behavior is most reliable
on a VM.
