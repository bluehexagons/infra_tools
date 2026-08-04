# Proxmox workflows

infra_tools can register Proxmox hosts, cache their capabilities, provision
Debian VMs or unprivileged LXCs, and manage guest lifecycle operations.
[Machine types](MACHINE_TYPES.md) explains the guest capability differences.

## Quick setup: Proxmox host to coding VM

Start from a current checkout on a trusted Linux orchestration machine. The
Proxmox host does not need a checkout; setup uploads the current source to
`/opt/infra_tools`.

```bash
git clone https://github.com/bluehexagons/infra_tools.git
cd infra_tools
git pull --ff-only
```

Register and inspect the host:

```bash
python3 infra_tools.py setup server_proxmox 10.0.0.10 root \
  --key ~/.ssh/proxmox_ed25519 \
  --name pve1

python3 infra_tools.py proxmox add pve1 10.0.0.10 \
  --user root --key ~/.ssh/proxmox_ed25519
python3 infra_tools.py proxmox probe pve1
python3 infra_tools.py proxmox top pve1
python3 infra_tools.py proxmox ls pve1
```

The public key must exist alongside the private key and root on the Proxmox
host must accept it.

Create a Debian VM with XFCE, RDP, Firefox, and coding tools:

```bash
python3 infra_tools.py setup workstation_dev 10.0.0.50 agent \
  --hosted pve1 --base debian --name agent-dev-01 \
  --cores 4 --memory 8G --storage root 40G \
  --desktop xfce --rdp --browser firefox \
  --agent-suite terminal --copy-config \
  --repo https://github.com/user/my_codebase.git \
  --node --go --python
```

Find the assigned VMID and inspect it:

```bash
python3 infra_tools.py proxmox ls pve1
python3 infra_tools.py proxmox config pve1 100
python3 infra_tools.py proxmox health pve1 100
```

Replace `100` with the VMID returned by `proxmox ls`.

## Hosted web server VM

```bash
python3 infra_tools.py setup server_web 10.0.0.50 admin \
  --hosted pve1 --memory 4G --storage root 32G --cores 2 \
  --base debian --name web-01-vm --ruby --node \
  --ssl --ssl-email admin@example.com \
  --deploy example.com https://github.com/user/repo.git
```

## Hosted LXC

Use `--machine unprivileged` explicitly for an LXC and include template
storage:

```bash
python3 infra_tools.py setup server_web 10.0.0.50 admin \
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

## Guest lifecycle

```bash
python3 infra_tools.py proxmox status pve1 101
python3 infra_tools.py proxmox start pve1 101
python3 infra_tools.py proxmox stop pve1 101
python3 infra_tools.py proxmox pause pve1 101
python3 infra_tools.py proxmox resume pve1 101
python3 infra_tools.py proxmox health pve1 101
```

Modify resources and configuration:

```bash
python3 infra_tools.py proxmox modify pve1 101 --cores 4 --memory 8G
python3 infra_tools.py proxmox reconfigure pve1 101 --set hostname=newbox
python3 infra_tools.py proxmox resize-disk pve1 101 rootfs 40G
```

Snapshots and rollback:

```bash
python3 infra_tools.py proxmox snapshots pve1 101
python3 infra_tools.py proxmox snapshot pve1 101 pre-upgrade --description "before kernel update"
python3 infra_tools.py proxmox rollback pve1 101 pre-upgrade
python3 infra_tools.py proxmox delsnapshot pve1 101 pre-upgrade
```

`destroy` is permanent and asks for confirmation:

```bash
python3 infra_tools.py proxmox destroy pve1 101
python3 infra_tools.py proxmox destroy pve1 101 -y
```

## Cluster and notifications

```bash
python3 infra_tools.py proxmox probe-cluster 10.0.0.10 \
  --key ~/.ssh/proxmox_ed25519 --tag prod
python3 infra_tools.py proxmox hosts
python3 infra_tools.py proxmox rolling-update pve1 pve2 pve3
python3 infra_tools.py proxmox notifications install-webhook \
  pve1 https://notify.example/hook --send-test
python3 infra_tools.py proxmox shell
```

`probe-cluster` discovers nodes from Proxmox's configured names and seeds the
host registry. `rolling-update` reuses saved setup commands and workspace
credentials, validates every target first, and waits for required reboots.

## Network planning

Use the separate [Network inventory](NETWORKING.md) workflow to build a
workspace-scoped inventory and render a read-only Proxmox firewall plan before
applying any control-plane lockdown.

## Real-system smoke test

For a first rollout, validate one VM and one LXC compatibility path:

```bash
infra_tools proxmox add pve1 10.0.0.10 --user root --key ~/.ssh/proxmox_ed25519
infra_tools proxmox probe pve1

infra_tools setup workstation_dev 10.0.0.50 devuser \
  --hosted pve1 --memory 8G --storage root 40G --cores 4 \
  --name dev-01-vm --rdp

infra_tools proxmox ls pve1
infra_tools proxmox health pve1 <vmid>
infra_tools proxmox snapshot pve1 <vmid> pre-modify
infra_tools proxmox modify pve1 <vmid> --cores 6 --memory 12G
infra_tools proxmox stop pve1 <vmid>
infra_tools proxmox start pve1 <vmid>

infra_tools setup server_lite 10.0.0.60 appuser \
  --machine unprivileged --hosted pve1 \
  --memory 2G --storage root 10G --storage template
```

For the VM path, verify SSH and optional RDP access. For LXC, focus on basic
provisioning and guest management; advanced desktop behavior is most reliable
on a VM.
