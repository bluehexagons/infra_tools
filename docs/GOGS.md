# Gogs Git service

`--gogs` installs a minimal self-hosted Gogs instance with Git-over-SSH, Git
LFS over HTTP/HTTPS, SQLite storage, nginx integration when a hostname is
supplied, and a managed weekly release update. The setup creates the `git`
system account with `git-shell`; it cannot be used as a general login account.

## Choose a deployment mode

Hostname mode is the usual choice. Gogs listens on localhost and nginx serves
the public URL:

```bash
infra-tools setup server_web git.example.com deploy \
  --gogs git.example.com:3000 /var/lib/gogs \
  --ssl --ssl-email admin@example.com
```

With `--ssl`, infra-tools obtains and renews a Let's Encrypt certificate. With
`--cloudflare`, the nginx-to-Gogs connection remains private and the tunnel
serves the hostname; public HTTP/HTTPS firewall ports are not opened. Direct
hostname deployments redirect ordinary port-80 requests to HTTPS, while the
Cloudflare-only HTTP origin remains unreachable outside the tunnel.

For a lab or private-network service, omit the hostname. With no source rules,
Gogs stays on loopback and setup prints an SSH tunnel command:

```bash
infra-tools setup server_web 192.168.1.10 deploy \
  --gogs :3000 /srv/gogs-data

ssh -L 3000:127.0.0.1:3000 deploy@192.168.1.10
```

To make plaintext HTTP reachable on a trusted private network, repeat
`--gogs-source` for the exact IPv4 hosts or networks that need access:

```bash
infra-tools setup server_web 192.168.1.10 deploy \
  --gogs :3000 /srv/gogs-data \
  --gogs-source 192.168.1.0/24 \
  --gogs-source 10.0.0.0/8
```

Source-restricted mode requires active UFW. Setup stops the existing Gogs
service, installs and verifies replacement source rules, removes obsolete
infra-tools-managed rules, and only then writes a non-loopback listener. It
refuses public IPv4 sources, IPv6 sources in this release, and unmanaged allow
rules for the same port. A source rule does not encrypt traffic; use hostname
mode with `--ssl` or `--cloudflare` across untrusted networks. Hostname mode
requires one of those encrypted ingress options. Switching between hostless,
hostname, and Cloudflare modes removes obsolete managed direct-access rules,
including dormant rules while UFW is installed but inactive.

The port defaults to 3000, so `--gogs 3000` is also valid. The optional data
path must be absolute and defaults to `/var/lib/gogs`.

## First login and Git access

Registration is disabled. Setup creates the initial administrator named by
the setup username and writes the generated password to the root-only file
`/opt/infra_tools/state/gogs_admin_credentials.json`; retrieve it locally on
the target and rotate it after the first login. The generated password has 24
random characters. Use another unique, high-entropy value when rotating it and
enable MFA for administrator accounts.

Hostname deployments throttle password and MFA submission endpoints to five
requests per minute per client with a small burst. Nginx also emits a
privacy-preserving marker for failed current-API web authentication and all
HTTP Basic authentication; five failures within ten minutes produce a one-hour
Fail2ban source ban. This covers Git/LFS and API Basic Auth without throttling
successful high-volume transfers.
Both the current Gogs API sign-in paths and the login/MFA paths used by older
managed releases receive the request limit. Cloudflare deployments derive the
client address from the trusted tunnel header. Direct hostless mode does not
pass through Nginx, so retain its private source restriction or use the default
SSH tunnel.

The web UI manages repository users and their SSH keys. Clone over HTTPS using
the configured hostname, or over SSH through the `git` account:

```bash
git clone https://git.example.com/team/project.git
git clone git@git.example.com:team/project.git
```

The SSH drop-in at `/etc/ssh/sshd_config.d/99-gogs-git-user.conf` permits
public-key Git operations for `git` while disabling passwords, forwarding, and
interactive sessions. Keep TCP port 22 reachable when SSH cloning is needed.

## Data, service, and updates

The selected data directory contains `custom/conf/app.ini`, the SQLite
database under `data/gogs.db`, repositories, logs, completed LFS objects under
`data/lfs-objects`, and temporary LFS uploads under
`data/tmp/lfs-objects`. Gogs uses its local LFS backend explicitly; no separate
LFS daemon or object store is required. Release binaries live under
`/opt/gogs/releases`; `/opt/gogs/current` and `/usr/local/bin/gogs` point to
the active release. Infra-tools requires the SHA-256 supplied in GitHub's
release asset metadata and verifies the downloaded archive before extracting
or activating it. A failed activation restores the prior verified release;
if no verified rollback target exists, setup stops the service. Setup also
refuses to replace an active release whose digest-qualified path disagrees
with the saved state; repair or restore that root-owned state before retrying.
Setup and patch also run a SQLite quick check, verify that the `git` user can
read and write each managed
directory, reject CIFS/SMB live storage, and print the backing filesystem, free
bytes, free inodes, and repository/LFS/attachment/log usage. Useful checks are:

```bash
sudo systemctl status gogs
sudo fail2ban-client status infra-tools-gogs
sudo journalctl -u gogs -n 100 --no-pager
sudo /usr/local/bin/gogs --version
infra-tools gogs health git.example.com
infra-tools gogs health git.example.com --json
```

Run `infra-tools gogs health` on the control system. It reads the root-owned
managed state through non-interactive sudo and reports service and SQLite
health, the backing filesystem, free bytes and inodes, per-category usage,
directory access as `git`, the update service/timer, nginx's upload limit, and
whether a non-loopback LFS HTTP endpoint is configured. It does not perform a
client-side network or authentication probe, so “configured” is not a claim
that DNS, routing, an external firewall, or credentials work. Defaults require
at least 1 GiB and 10,000 inodes free; override them with `--min-free-bytes`
and `--min-free-inodes`. The check is read-only and never prunes LFS objects.

`auto-update-gogs.timer` checks weekly (Sunday at 05:30). It validates the
downloaded binary from a private, randomly named temporary workspace, refreshes
authorized keys and hooks, restarts Gogs, and updates the saved state only after
success. If a post-update command, restart, or state write fails, the previous
release symlink is restored and a failure notification is emitted when
notifications are configured. Every completed check records a root-owned
result in `/opt/infra_tools/state/gogs_update.json`; health fails when the last
result failed or the record (falling back to initial setup state before the
first timer run) is older than nine days.

Run the normal `patch` flow to reapply the saved Gogs configuration. Do not
edit `app.ini` while the service is running unless you understand that a later
patch rewrites the managed settings. Back up the entire data directory before
database or repository maintenance; release updates do not replace it.

Gogs transfers LFS objects over HTTP/HTTPS even when ordinary Git uses an SSH
remote, so clients still need credentials and network access to the Gogs web
URL. Gogs does not provide Git LFS file locking. Treat repositories, SQLite,
configuration, and completed LFS objects as one recovery set; do not copy
those live paths independently and call the result a consistent backup.

Agent VMs that need LFS can install and initialize the client once before all
normal repository clones:

```bash
infra-tools setup server_dev 192.168.1.41 agent \
  --git-lfs \
  --repo https://git.example.com/team/assets.git
```

`--git-lfs` does not alter repository URLs or credentials. A loopback-only
Gogs deployment is not remotely LFS-ready unless the client has a persistent
HTTP tunnel and a matching repository LFS URL; routine LFS use should use the
HTTPS hostname mode or source-restricted private listener.

## Dedicated VM data disk

For a newly provisioned QEMU VM, the Gogs data root can be a required local
data mount:

```bash
infra-tools setup server_web 192.168.1.10 deploy \
  --provision-on pve1 --memory 4G --storage root 32G \
  --storage git-data bulk-lvm 128G \
  --storage-mount git-data /srv/gogs ext4 \
  --gogs git.example.com:3000 /srv/gogs \
  --ssl --ssl-email admin@example.com
```

The disk is identified by a stable serial, formatted only when confirmed
blank, and mounted by filesystem UUID before Gogs creates any data. Gogs then
checks the marker on that mounted filesystem and applies `git:git` ownership.
A missing or wrong mount stops setup instead of allowing repositories or LFS
objects to spill onto the root disk.

This automation is for blank disks allocated with the new VM. It does not
adopt an existing disk, migrate populated Gogs data, or put live Gogs data on
CIFS/Samba. Samba is appropriate for a consistent offline archive or export,
not as the live SQLite, repository, or LFS-object filesystem.

## Troubleshooting

- A hostname setup that fails nginx validation fails setup and leaves Gogs
  stopped unless a prior verified release can be restored; run `sudo nginx -t`
  and inspect the generated `gogs_<hostname>` site before retrying.
- A hostless source setup fails closed when UFW is inactive or another rule
  already exposes the selected port. Inspect `sudo ufw status numbered` before
  retrying.
- A failed Git-over-SSH clone usually means the user's public key is missing or
  port 22 is blocked; check the SSH drop-in and `journalctl -u ssh`.
- If the web service is down, inspect `journalctl -u gogs` and verify ownership
  of the data directory (`git:git`).
- Check the update timer with `sudo systemctl status auto-update-gogs.timer`
  and its last run with `sudo journalctl -u auto-update-gogs.service`.

See [`COMMAND_LINE.md`](./COMMAND_LINE.md) for the complete flag syntax and
[`MAINTENANCE.md`](./MAINTENANCE.md) for timer policy.
