# Machine Types

The `--machine` flag specifies the environment type, enabling setup commands to
adapt configuration based on platform capabilities. The default is `auto`, so
the remote setup process makes a best-effort guess from the target runtime.

## Officially Supported Configurations

infra_tools officially supports Debian in these configurations:

- **Bare metal**: a physical Debian host, detected as `hardware`.
- **Virtual machine**: a Debian VM on Proxmox or a hosted VPS such as
  DigitalOcean, detected as `vm`.
- **Proxmox LXC**: an unprivileged Debian LXC container, detected as
  `unprivileged`.

The detection is deliberately conservative. Use an explicit `--machine` value
when the runtime cannot identify itself reliably or when an existing setup has
a special requirement. OCI containers and privileged LXCs remain recognized
compatibility labels, but they are not part of the official support target.

## Types

| Type | Description | Example |
|------|-------------|---------|
| `auto` | Detect the target runtime and select a safe supported profile | Default |
| `unprivileged` | Unprivileged LXC container for lightweight compatibility use | Proxmox LXC |
| `vm` | Virtual machine | Proxmox VM or DigitalOcean VPS |
| `hardware` | Bare metal | Physical server |
| `privileged` | Privileged LXC container (compatibility label) | Proxmox LXC with passthrough |
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

- Direct setup and patch flows default to `auto` and resolve the machine type
  on the target before setup steps run.
- `auto` resolves to `hardware`, `vm`, or `unprivileged` for the officially
  supported configurations.
- Hosted Proxmox provisioning defaults to a VM because the guest does not exist
  yet; use `--machine unprivileged` to provision an LXC instead.
- `server_proxmox` also uses `auto` and normally resolves to `hardware` on the
  Proxmox host itself.

## Existing Saved Configurations

Saved configurations retain their explicit machine type. New commands use
`auto`, while an older saved `vm`, `hardware`, or `unprivileged` selection is
preserved when patching or deploying. This avoids changing the behavior of
existing hosts unexpectedly.

For saved configurations, prefer `infra_tools deploy <name-or-host>` or
`infra_tools patch <host>` over retyping old commands. `infra_tools cmd
<name-or-host>` prints an explicit override when the saved configuration is not
using the new `auto` default.

Proxmox host setup normally resolves to `hardware`, with normal automatic
restarts disabled by default and a 7-day forced restart deadline.

## Usage

```bash
# Auto-detect the target (the normal direct-setup path)
python3 infra_tools.py setup workstation_dev 192.168.1.10

# Force an officially supported Proxmox LXC profile
python3 infra_tools.py setup workstation_dev 192.168.1.10 --machine unprivileged

# Explicit machine types when needed
python3 infra_tools.py setup workstation_dev 192.168.1.10 --machine privileged
python3 infra_tools.py setup server_web 192.168.1.20 --machine hardware

# OCI container (limited features)
python3 infra_tools.py setup server_lite 192.168.1.30 --machine oci
```

## Provisioning a Proxmox VM

Hosted flows default to VMs when you use `--hosted`, so you can provision a VM
via `qm` + cloud-init without adding `--machine vm`:

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
