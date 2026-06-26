# Machine Types

The `--machine` flag specifies the environment type, enabling setup commands to adapt configuration based on platform capabilities.

## Types

| Type | Description | Example |
|------|-------------|---------|
| `unprivileged` | Unprivileged LXC container for lightweight compatibility use | Proxmox LXC |
| `vm` | Virtual machine (preferred for most hosted workstation/web/build flows) | Proxmox VM |
| `privileged` | Privileged LXC container | Proxmox LXC with passthrough |
| `hardware` | Bare metal | Physical server |
| `oci` | OCI container | Docker, Podman |

## Capability Matrix

| Capability | unprivileged | vm | privileged | hardware | oci |
|------------|--------------|-----|------------|----------|-----|
| GPU/DRI access | ❌ | ✅ | ✅ | ✅ | ❌ |
| Kernel parameters | ❌ | ✅ | ✅ | ✅ | ❌ |
| Firewall (UFW) | ❌ | ✅ | ✅ | ✅ | ❌ |
| Swap configuration | ❌ | ✅ | ✅ | ✅ | ❌ |
| Time sync (chrony) | ❌ | ✅ | ✅ | ✅ | ❌ |
| System restart | ✅ | ✅ | ✅ | ✅ | ❌ |

## Behavior

### Unprivileged/OCI Containers
- **Skipped**: Swap, kernel hardening (sysctl), time sync, fail2ban
- **Attempted with graceful failure**: Firewall (UFW), auto-updates
- **XRDP**: Software rendering mode (no GPU access)
- **Flatpak**: Warns and falls back to apt

### VM/Privileged/Hardware
- All features enabled
- GPU-accelerated XRDP when available
- Full system control

## Default Resolution

- setup flows default to `vm` unless the system type has an explicit override
- `server_proxmox` defaults to `hardware`
- `--build-server` also defaults to `vm`
- use `--machine unprivileged` to force an LXC on a VM-first workflow

## Upgrade Notes For Main-Era LXC Systems

Older `main` setups commonly relied on the global `unprivileged` default for
hosted `server_web`, `server_dev`, `workstation_desktop`, `workstation_dev`, and `pc_dev`
commands. On this branch setup flows are VM-first by default, so copied
single-system LXC commands for existing systems must add `--machine unprivileged`
before rerunning setup.

For saved configurations, prefer `infra_tools deploy <name-or-host>` or
`infra_tools patch <host>` over retyping old commands. Saved configs include the
machine type, patch preserves it when `--machine` is omitted, and
`infra_tools cmd <name-or-host>` prints `--machine unprivileged` for LXC systems
whose current setup default is VM.

Proxmox host setup does not need a migration flag: `server_proxmox` remains a
hardware flow with normal automatic restarts disabled by default and a 7-day
forced restart deadline. Bring those hosts up to date by rerunning the saved
setup or patch command normally.

## Usage

```bash
# VM-first workstation default
python3 infra_tools.py setup workstation_dev 192.168.1.10

# Force LXC compatibility mode on a VM-first workflow
python3 infra_tools.py setup workstation_dev 192.168.1.10 --machine unprivileged

# Explicit machine type
python3 infra_tools.py setup workstation_dev 192.168.1.10 --machine privileged
python3 infra_tools.py setup server_web 192.168.1.20 --machine hardware

# OCI container (limited features)
python3 infra_tools.py setup server_lite 192.168.1.30 --machine oci
```

## Provisioning a Proxmox VM

Hosted flows now default to VMs when you use `--hosted`, so you can provision a
VM via `qm` + cloud-init without adding `--machine vm`:

```bash
python3 infra_tools.py setup server_web 10.0.0.50 \
    --hosted proxmox.lan \
    --memory 4G --cores 2 \
    --storage root local-lvm 32G
```

Use `--machine unprivileged` to stay on the LXC path.

For raw Proxmox addresses, storage shorthand falls back to `auto`. For
registered hosts, shorthand uses the saved/probed storage defaults first.

By default, the curated Debian cloud-image catalog
(`lib/cloud_images.py`) supplies the qcow2. Override with `--image`:

```bash
# Direct URL
... --image https://cloud.debian.org/.../debian-12-genericcloud-amd64.qcow2

# Pre-uploaded image on the Proxmox node
... --image local:iso/my-debian.qcow2
```

Refresh the catalog with `python3 scripts/update_cloud_images.py`. Add
`--pin-snapshot` to lock entries to a specific upstream snapshot directory and
record its SHA-512.

## State Persistence

Machine type is saved to `/opt/infra_tools/state/machine.json` on target systems, allowing service scripts to adapt behavior automatically.
