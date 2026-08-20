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
serves the hostname; public HTTP/HTTPS firewall ports are not opened.

For a lab or private-network service, omit the hostname and expose Gogs
directly on its port:

```bash
infra-tools setup server_web 192.168.1.10 deploy \
  --gogs :3000 /srv/gogs-data
```

Hostless mode binds directly to `0.0.0.0:<port>` and opens that port only when
UFW is already active. The port defaults to 3000, so `--gogs 3000` is also
valid. The optional data path must be absolute and defaults to
`/var/lib/gogs`.

## First login and Git access

Registration is disabled. Setup creates the initial administrator named by
the setup username and writes the generated password to the root-only file
`/opt/infra_tools/state/gogs_admin_credentials.json`; retrieve it locally on
the target and rotate it after the first login.

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
the active validated release. Useful checks are:

```bash
sudo systemctl status gogs
sudo journalctl -u gogs -n 100 --no-pager
sudo /usr/local/bin/gogs --version
```

`auto-update-gogs.timer` checks weekly (Sunday at 05:30). It validates the
downloaded binary from a private, randomly named temporary workspace, refreshes
authorized keys and hooks, restarts Gogs, and updates the saved state only after
success. If a post-update command, restart, or state write fails, the previous
release symlink is restored and a failure notification is emitted when
notifications are configured.

Run the normal `patch` flow to reapply the saved Gogs configuration. Do not
edit `app.ini` while the service is running unless you understand that a later
patch rewrites the managed settings. Back up the entire data directory before
database or repository maintenance; release updates do not replace it.

Gogs transfers LFS objects over HTTP/HTTPS even when ordinary Git uses an SSH
remote, so clients still need credentials and network access to the Gogs web
URL. Gogs does not provide Git LFS file locking. Treat repositories, SQLite,
configuration, and completed LFS objects as one recovery set; do not copy
those live paths independently and call the result a consistent backup.

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

- A hostname setup that fails nginx validation leaves the service local; run
  `sudo nginx -t` and inspect the generated `gogs_<hostname>` site.
- A failed Git-over-SSH clone usually means the user's public key is missing or
  port 22 is blocked; check the SSH drop-in and `journalctl -u ssh`.
- If the web service is down, inspect `journalctl -u gogs` and verify ownership
  of the data directory (`git:git`).
- Check the update timer with `sudo systemctl status auto-update-gogs.timer`
  and its last run with `sudo journalctl -u auto-update-gogs.service`.

See [`COMMAND_LINE.md`](./COMMAND_LINE.md) for the complete flag syntax and
[`MAINTENANCE.md`](./MAINTENANCE.md) for timer policy.
