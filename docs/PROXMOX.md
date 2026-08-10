# Proxmox workflows

infra_tools can register Proxmox hosts, cache their capabilities, provision
Debian VMs or unprivileged LXCs, and manage guest lifecycle operations.
[Machine types](MACHINE_TYPES.md) explains the guest capability differences.

## Quick setup: Proxmox host to coding VM

Install infra_tools on a trusted Linux orchestration machine first. The
Proxmox host does not need a checkout; setup uploads the installed source to
`/opt/infra_tools`.

```bash
curl -fsSL https://raw.githubusercontent.com/bluehexagons/infra_tools/main/install.sh | sh
infra_tools channel
```

Set up, register, and inspect the host:

```bash
infra_tools setup server_proxmox 10.0.0.10 root \
  --key ~/.ssh/proxmox_ed25519 \
  --name pve1

infra_tools proxmox probe pve1
infra_tools proxmox top pve1
infra_tools proxmox ls pve1
```

Successful `server_proxmox` setup registers the host in the selected workspace;
`--name` supplies the registry name and defaults to the host address when omitted.

The matching `.pub` file must sit beside the private key, and the Proxmox
`root` account must accept that key.

Hosted VM setup uses the same private key's `.pub` file for cloud-init. If the
Proxmox node key and guest key differ, pass `--hosted-key` for the node and
`--key` for the guest. Hosted VM image downloads and cloud-init snippets are
placed through Proxmox storage APIs, so the selected node must have active
`iso` and `snippets` storage content types.

## Host-safety defaults

The `server_proxmox` flow deliberately leaves firewall policy to Proxmox and
does not create a generic `/swapfile`: Proxmox storage (especially ZFS) must
own its swap layout. It retains the host's permissive reverse-path filtering
because strict filtering can drop valid routed, NATed, or bridged guest
traffic. Configure host/guest firewall rules through the Proxmox firewall
workflow after confirming management-network access.

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
  old crash reports, and infra_tools-owned temporary artifacts, and ensures
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
infra_tools setup workstation_dev 10.0.0.50 agent \
  --hosted pve1 --base debian --name agent-dev-01 \
  --cores 4 --memory 8G --storage root 40G \
  --desktop xfce --rdp --browser firefox \
  --password "$RDP_PASSWORD" \
  --agent-suite terminal --copy-config \
  --repo https://github.com/user/my_codebase.git \
  --node --go --python
```

Find the assigned VMID and inspect it:

```bash
infra_tools proxmox ls pve1
infra_tools proxmox config pve1 100
infra_tools proxmox health pve1 100
```

Replace `100` with the VMID returned by `proxmox ls`.

`--rdp` requires `--password` for the non-root desktop account. Set
`RDP_PASSWORD` in a secure secret source rather than placing a literal in
shell history; the password is not persisted in saved setup state.

## Graphical VM hardware baseline

Hosted VMs that include a desktop or enable RDP are created with both a
VirtIO-GPU display and a serial socket. The VirtIO device supplies a usable
Proxmox noVNC recovery console; the serial socket remains available for boot
diagnostics. Server-only VMs retain `vga: serial0` to avoid an unused emulated
display. Existing desktop VMs created with a serial-only display can be shut
down and changed with `qm set VMID --vga virtio` on the Proxmox node.

The emulated display does **not** accelerate an XRDP session. xorgxrdp creates
its own resizable X.Org display with the `xrdpdev` driver, and infra_tools keeps
that path software-rendered for compatibility. Accordingly, setup does not add
the desktop user to `video` or `render` merely because the target is a VM.

The resulting Proxmox baseline is:

| Setting | infra_tools default | Rationale / alternative |
| --- | --- | --- |
| Display | VirtIO-GPU for desktop/RDP; serial-only for servers | VirtIO-GPU is a recovery console, not XRDP acceleration. QXL/SPICE and `virtio-gl` add no benefit to this RDP path. |
| Serial | `serial0: socket` | Retains low-level diagnostics alongside the graphical console. |
| CPU | `host` | Best performance on one node or a CPU-homogeneous cluster. Use a compatible `x86-64-v*` model when cross-generation live migration matters. |
| Machine/firmware | Proxmox defaults | Q35/OVMF are not required for an emulated display or XRDP; prefer them when PCIe GPU passthrough requires them. |
| Disk controller | VirtIO SCSI single with `iothread=1` on the root disk | Uses the per-disk I/O thread supported by the selected controller. Enable discard/SSD flags only when the backing storage policy supports them. |
| Network | VirtIO | Lowest-overhead normal Linux guest path. Multiqueue is normally unnecessary for interactive RDP traffic. |
| Guest agent | Enabled and installed | Supports clean lifecycle and guest inspection from Proxmox. |
| Memory | Fixed requested allocation | Start around 8 GiB for the documented coding desktop and size for browsers, editors, builds, and agents; do not rely on aggressive overcommit for interactive latency. |

These choices follow Proxmox's documented VirtIO network and VirtIO-SCSI
performance guidance and its warning that `host` CPU trades migration
portability for host feature exposure. Proxmox also documents that selecting a
serial display disables VGA output. See the current
[Proxmox VE administration guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.pdf).

Physical GPU passthrough is a different profile. It needs host IOMMU/device
isolation, usually Q35/OVMF, explicit guest drivers, and separate xorgxrdp
glamor compatibility testing. It is not enabled by the default RDP setup.

## Hosted web server VM

```bash
infra_tools setup server_web 10.0.0.50 admin \
  --hosted pve1 --memory 4G --storage root 32G --cores 2 \
  --base debian --name web-01-vm --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

## Hosted LXC

Use `--machine unprivileged` explicitly for an LXC and include template
storage:

```bash
infra_tools setup server_web 10.0.0.50 admin \
  --machine unprivileged --hosted pve1 \
  --memory 4G --cores 2 --storage root 20G --storage template \
  --base debian --name web-01-lxc --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

`--storage` is repeatable. Root storage accepts `--storage root POOL AMOUNT`
or the shorthand `--storage root AMOUNT`, which uses cached host defaults or
Proxmox auto-detection. `--storage template` uses the saved/default template
pool.
The guest bridge defaults to the bridge carrying the Proxmox host's default
route; use `--bridge NAME` when the host has multiple routed bridge networks.

## Guest lifecycle

```bash
infra_tools proxmox status pve1 101
infra_tools proxmox start pve1 101
infra_tools proxmox stop pve1 101
infra_tools proxmox pause pve1 101
infra_tools proxmox resume pve1 101
infra_tools proxmox health pve1 101
```

Show a summary for one or more nodes:

```bash
infra_tools proxmox top pve1 pve2
```

The summary includes node CPU, memory, storage, and guest counts. It is a
read-only health and capacity view; `probe` should be run first when a host's
storage or bridge data has not been cached.

Run a maintenance-safety audit before planned work:

```bash
infra_tools proxmox audit pve1 pve2
infra_tools proxmox audit pve1 --json
```

The audit checks core Proxmox services, quorum on clustered nodes, active tasks,
configured storage, at least 4 GiB of free root space, guest locks, running
guests, and whether a reboot is pending. Text output distinguishes general
health from reboot safety; JSON output is intended for automation. The command
is read-only and exits nonzero when a health check fails.

Modify resources and configuration:

```bash
infra_tools proxmox modify pve1 101 --cores 4 --memory 8G
infra_tools proxmox reconfigure pve1 101 --set hostname=newbox
infra_tools proxmox resize-disk pve1 101 rootfs 40G
```

Snapshots and rollback:

```bash
infra_tools proxmox snapshots pve1 101
infra_tools proxmox snapshot pve1 101 pre-upgrade --description "before kernel update"
infra_tools proxmox rollback pve1 101 pre-upgrade
infra_tools proxmox delsnapshot pve1 101 pre-upgrade
```

`destroy` is permanent and asks for confirmation:

```bash
infra_tools proxmox destroy pve1 101
infra_tools proxmox destroy pve1 101 -y
```

## Placement, backups, and migration

The placement planner ranks registered nodes without changing them:

```bash
infra_tools proxmox plan place \
  --cores 4 --memory 8192 --disk 40 \
  --prefer-tag production --exclude pve3
infra_tools proxmox plan rebalance --limit 3
```

`plan rebalance` reports overloaded nodes and candidate destinations. It only
migrates when `--apply VMID` is supplied; use `--dry-run` to preview the
migration command and `--yes` to skip its confirmation prompt. `--to HOST`
overrides the top-ranked destination. Online migration and local-disk transfer
have the same storage and cluster prerequisites as the direct `migrate` command.

List and create immediate `vzdump` backups:

```bash
infra_tools proxmox backups pve1 101
infra_tools proxmox backup pve1 101 \
  --storage backup --mode snapshot --compress zstd --dry-run
```

The backup command defaults to the first backup-capable storage pool, snapshot
mode, and zstd compression. `suspend` and `stop` modes trade availability for
stronger consistency where the guest workload requires it. Always verify that
the selected storage has enough capacity and a retention policy outside
infra_tools.

Migrate a guest between registered cluster nodes:

```bash
infra_tools proxmox migrate pve1 101 pve2 --dry-run
infra_tools proxmox migrate pve1 101 pve2 \
  --online --with-local-disks
```

`--online` keeps a VM running and requires suitable shared or migrated storage.
`--with-local-disks` copies local disks to target-node storage. Use the dry run
first for production migrations.

## Orphaned volumes and stuck locks

List unreferenced guest volumes before deleting anything:

```bash
infra_tools proxmox clean-disks pve1 --dry-run
infra_tools proxmox clean-disks pve1 --delete
```

`clean-disks` is list-only by default. `--delete` requires typing `yes` unless
`--yes`/`-y` is supplied; treat it as destructive because an orphaned-volume
check cannot infer whether an external workflow still needs a volume.

After confirming that no backup, migration, or snapshot task is still active,
clear a stale Proxmox management lock:

```bash
infra_tools proxmox unlock pve1 101 --dry-run
infra_tools proxmox unlock pve1 101
```

The unlock operation only clears the guest lock; it does not repair a failed
underlying task or roll back partial storage changes.

## Cluster and notifications

```bash
infra_tools proxmox probe-cluster 10.0.0.10 \
  --key ~/.ssh/proxmox_ed25519 --tag prod
infra_tools proxmox hosts
infra_tools proxmox audit pve1 pve2 pve3
infra_tools proxmox rolling-update pve1 pve2 pve3
infra_tools proxmox notifications install-webhook \
  pve1 https://notify.example/hook --send-test
infra_tools proxmox notifications test-webhook pve1
infra_tools proxmox shell
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
infra_tools proxmox hosts
infra_tools proxmox probe pve1

infra_tools setup workstation_dev 10.0.0.50 devuser \
  --hosted pve1 --memory 8G --storage root 40G --cores 4 \
  --name dev-01-vm --rdp

infra_tools proxmox ls pve1
VMID=100  # replace with the VMID returned by `infra_tools proxmox ls`
infra_tools proxmox health pve1 "$VMID"
infra_tools proxmox snapshot pve1 "$VMID" pre-modify
infra_tools proxmox modify pve1 "$VMID" --cores 6 --memory 12G
infra_tools proxmox stop pve1 "$VMID"
infra_tools proxmox start pve1 "$VMID"

infra_tools setup server_lite 10.0.0.60 appuser \
  --machine unprivileged --hosted pve1 \
  --memory 2G --storage root 10G --storage template
```

For the VM path, verify SSH and optional RDP access. For LXC, focus on basic
provisioning and guest management; advanced desktop behavior is most reliable
on a VM.
