# Network Inventory and Proxmox Firewall Planning

The `network` command manages a workspace-backed, provider-neutral network
inventory and can generate a read-only Proxmox control-plane firewall plan from
that inventory.

## Current Scope

Implemented today:

- create and inspect named network profiles
- track management sources, control-plane addresses, guest networks, subnets,
  VLAN-tagged subnets, and hosts
- import registered Proxmox nodes into a profile
- import guest networks discovered from registered Proxmox hosts
- generate an abstract Proxmox lockdown plan or render concrete Proxmox
  firewall snippets for review

Not implemented yet:

- remote `apply` or `rollback`
- switch, router, or cloud provider adapters
- live discovery beyond the current Proxmox registry and guest config import

Inventory is stored at `<workspace>/network_inventory.json` with mode `0600`.
Like other workspace-scoped features, pass `--workspace PATH` after `network`
to isolate data for a project or environment.

## Common Workflow

1. Create a profile and seed it with at least one management source.
2. Add manual hosts or import known Proxmox nodes.
3. Import guest networks from the registered Proxmox hosts.
4. Review the generated lockdown plan before touching any firewall config.

```bash
# Create a profile
infra_tools.py network init homelab \
  --management 192.168.1.0/24 \
  --control-plane 10.0.0.10 \
  --guest-network 10.0.10.0/24

# Add metadata manually when needed
infra_tools.py network add-host homelab pve1 10.0.0.10 \
  --provider proxmox \
  --role control-plane \
  --role proxmox

# Or import from the saved Proxmox host registry
infra_tools.py network import-proxmox homelab --tag prod
infra_tools.py network import-proxmox-guests homelab --tag prod

# Review the abstract plan
infra_tools.py network plan-proxmox homelab

# Render the matching Proxmox snippets without applying them
infra_tools.py network plan-proxmox homelab --proxmox
```

## Commands

| Command | Purpose |
|---------|---------|
| `infra_tools.py network list` | List saved network profiles |
| `infra_tools.py network show <profile>` | Show one profile in text form |
| `infra_tools.py network show <profile> --json` | Dump one profile as JSON |
| `infra_tools.py network init <profile> [...]` | Create a profile with management, control-plane, guest-network, subnet, or VLAN entries |
| `infra_tools.py network add-host <profile> <name> <address> [...]` | Add a tagged host record to a profile |
| `infra_tools.py network import-proxmox <profile> [...]` | Import registered Proxmox nodes into the profile |
| `infra_tools.py network import-proxmox-guests <profile> [...]` | Import guest networks from registered Proxmox hosts |
| `infra_tools.py network plan-proxmox <profile>` | Print the abstract read-only lockdown plan |
| `infra_tools.py network plan-proxmox <profile> --proxmox` | Render concrete Proxmox firewall artifacts for review |
| `infra_tools.py network plan-proxmox <profile> --json` | Emit machine-readable JSON |

## Safety Model

`plan-proxmox` is intentionally read-only. It never writes remote files or talks
to the Proxmox firewall API.

The planner refuses to produce an apply-safe result until the profile includes:

- at least one management source
- at least one control-plane address

If guest networks are missing, the planner still renders a warning so you can
see that the guest-to-control-plane deny rule has no source set yet.

`plan-proxmox --proxmox` renders the artifacts that would back the policy:

- `/etc/pve/firewall/cluster.fw`
- `/etc/pve/nodes/<node>/host.fw`
- `/etc/pve/firewall/<VMID>.fw`

Use these outputs for review, diffing, or future automation; the current CLI
does not apply them for you.
