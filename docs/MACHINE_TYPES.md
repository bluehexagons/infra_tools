# Machine Types

The `--machine` flag specifies the environment type, enabling setup scripts to adapt configuration based on platform capabilities.

## Types

| Type | Description | Example |
|------|-------------|---------|
| `unprivileged` | Unprivileged LXC container (default) | Proxmox LXC |
| `vm` | Virtual machine | Proxmox VM |
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

## Usage

```bash
# Unprivileged LXC (default)
python3 setup_workstation_dev.py 192.168.1.10

# Explicit machine type
python3 setup_workstation_dev.py 192.168.1.10 --machine vm
python3 setup_workstation_dev.py 192.168.1.10 --machine privileged
python3 setup_server_web.py 192.168.1.20 --machine hardware

# OCI container (limited features)
python3 setup_server_lite.py 192.168.1.30 --machine oci
```

## State Persistence

Machine type is saved to `/opt/infra_tools/state/machine.json` on target systems, allowing service scripts to adapt behavior automatically.
