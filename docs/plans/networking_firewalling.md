# Generic Networking And Firewalling

## Goal

Build a guided networking and firewalling layer that can model mixed environments,
then apply provider-specific enforcement where support exists. Proxmox should be a
first-class provider, but the core concepts should remain generic enough for
standalone Linux hosts, routers, managed switches, and future cloud targets.

The first high-value use case is locking down a Proxmox cluster so hosted VMs and
containers cannot reach cluster control-plane services unless explicitly allowed.

## Core Model

The shared model should describe intent, not Proxmox implementation details:

- Network profiles: named environments such as `homelab`, `prod`, or `lab`.
- Zones: management, control plane, guests, storage, public edge, backup, and
  application tiers.
- Subnets: CIDR ranges with optional VLAN IDs, gateway, DNS, and zone labels.
- Hosts: named IPs with roles, provider metadata, and optional relation to saved
  infra_tools setups or Proxmox host records.
- Services: protocol/port bundles such as SSH, Proxmox API, SMB, HTTP, HTTPS, DNS,
  application ports, and internal management ports.
- Policies: directional connectivity intent between zones, hosts, subnets, and
  services.

Provider adapters should translate this model into concrete configuration.

## Initial Proxmox Behavior

The Proxmox adapter should discover:

- Cluster nodes from existing `proxmox probe-cluster` host records.
- Node IPs, bridges, default gateway, DNS, and storage networks when available.
- Guest VMID, guest type, configured IPs, bridges, tags, and current firewall state.
- VLAN-aware bridge configuration where it can be read safely.

The first generated policy should:

- Define management sources that may reach Proxmox control-plane ports.
- Define control-plane node IPs as an address set.
- Define guest subnets from known VM/CT networks.
- Drop guest-to-control-plane traffic by default.
- Allow management-to-control-plane traffic for required Proxmox, SSH, and
  cluster maintenance services.
- Optionally enable guest IP filtering so guests cannot spoof trusted addresses.

## Safety Requirements

- Default to planning and diffing. Applying changes must be explicit.
- Refuse to enable restrictive firewall policies without at least one management
  source.
- Backup every touched remote firewall file or API resource into the workspace.
- Keep rollback metadata with timestamp, profile name, provider, target host, and
  original content.
- Validate every user-provided IP, subnet, VLAN ID, service name, protocol, and port.
- Keep existing SSH/control sessions in mind and warn before changing management
  reachability.
- Avoid storing secrets in network inventory files.

## CLI Shape

Generic commands:

```bash
infra_tools.py network list
infra_tools.py network init homelab --management 192.168.1.0/24
infra_tools.py network add-host homelab pve1 10.0.0.10 --provider proxmox --role control-plane
infra_tools.py network import-proxmox homelab --tag prod
infra_tools.py network import-proxmox-guests homelab --tag prod
infra_tools.py network show homelab
```

Future planning and apply commands:

```bash
infra_tools.py network probe homelab --provider proxmox --from-host pve1
infra_tools.py network plan homelab --target proxmox-cluster
infra_tools.py network apply homelab --target proxmox-cluster
infra_tools.py network rollback homelab --target proxmox-cluster --timestamp ...
```

## Implementation Phases

1. Add generic network inventory persistence and validation.
2. Add generic CLI commands for listing, creating, showing, and updating profiles.
3. Add Proxmox discovery that imports registered cluster nodes and known guest
   networks into the generic inventory.
4. Add a read-only planner that emits Proxmox firewall intent without touching
   remote hosts.
5. Add diff, backup, apply, and rollback support.
6. Add an interactive wizard once the non-interactive planner is testable.

## Open Questions

- Whether provider metadata should reference saved setup configs by host address,
  friendly name, or an explicit stable ID.
- How much VLAN and switch state can be discovered reliably without requiring
  switch-specific credentials.
- Whether firewall policy should use an allow-list service model from day one, or
  start with a smaller deny-control-plane rule set and grow from there.
