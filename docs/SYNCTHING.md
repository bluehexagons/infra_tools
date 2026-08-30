# Managed Syncthing

The Syncthing integration provides private, bidirectional file exchange for a
known group of people without requiring a VPN or a publicly reachable server.
Each endpoint trusts explicit device IDs, and each folder names exactly which
declared devices may participate. Syncthing encrypts device-to-device traffic;
relay operators cannot read file contents.

Infra-tools manages one dedicated Syncthing instance on a Debian server or
workstation. The service runs as the non-root setup account, the admin UI binds
only to `127.0.0.1:8384`, automatic router port mappings are disabled, and no
firewall rule is added. Existing routing and firewall policy may still permit
direct connections; otherwise Syncthing uses its outbound relay fallback.

## Bootstrap the hub

Install the endpoint first so it can generate a stable device identity:

```bash
infra-tools setup server_lite fileserver admin --syncthing
```

Setup prints the server's full device ID. It also prints the SSH tunnel command
for its loopback-only admin UI. From the controller, use the actual setup host
and account:

```bash
ssh -L 8384:127.0.0.1:8384 admin@fileserver
```

Then open `http://127.0.0.1:8384`. The tunnel is for administration only;
coworkers do not need SSH or network access to the server.

Have each coworker install Syncthing and send you the full ID shown by their
client. They should add only the server ID to their client. They do not need to
add one another, which preserves the hub-and-spoke boundary.

## Declare peers and folders

Rerun setup with the complete peer and folder declaration:

```bash
infra-tools setup server_lite fileserver admin \
  --syncthing \
  --syncthing-device alice-laptop \
    S7UKX27-GI7ZTXS-GC6RKUA-7AJGZ44-C6NAYEB-HSKTJQK-KJHU2NO-CWV7EQW \
  --syncthing-device bob-desktop \
    5SYI2FS-LW6YAXI-JJDYETS-NDBBPIO-256MWBO-XDPXWVG-24QPUM4-PDW4UQU \
  --syncthing-folder send-receive shared-work \
    /srv/syncthing/shared-work alice-laptop,bob-desktop
```

The example IDs are illustrative; use the exact IDs copied from those clients.
Device names and folder IDs are local infra-tools identifiers and use lowercase
letters, numbers, dots, and hyphens. A folder path must be below the setup
user's home, `/data`, `/media`, `/mnt`, or `/srv`.

On each coworker's client, accept or create a folder with the same folder ID,
`shared-work`, choose any appropriate local path, and share it only with the
server. Their client can normally use **Send & Receive** for bidirectional work.

Folder modes are interpreted from the managed endpoint's perspective:

- `send-receive` sends local changes and accepts peer changes;
- `send-only` publishes local content without applying peer changes;
- `receive-only` accepts peer content without publishing local edits.

Repeat `--syncthing-folder` for project-scoped folders. The final `DEVICES`
argument is a comma-separated list without spaces and may contain only names
declared by `--syncthing-device`.

Infra-tools treats the devices and folders of this dedicated instance as a
complete declaration. A later setup that supplies declarations replaces the
managed set, so include every peer and folder that should remain. Changes made
directly in the Syncthing GUI are overwritten on the next infra-tools run.

## Version recovery

Staggered versioning is the default on every declared folder. It keeps older
versions with progressively wider spacing for up to one year. This is the
recommended hub setting because replacements and deletions arriving from a
coworker's device can be recovered from the hub's `.stversions` directory.

Choose another global policy when necessary:

```bash
--syncthing-versioning trashcan   # keep remote replacements/deletions for 30 days
--syncthing-versioning none       # disable Syncthing file versioning
```

Syncthing versioning is not an independent backup: it applies when another
device replaces or deletes a file, and all peers still share a trust domain.
Keep server snapshots or a separate backup for recovery from disk loss,
account compromise, or mistakes made directly on the hub.

## Service operations

```bash
sudo systemctl status infra-syncthing.service
sudo journalctl -u infra-syncthing.service -n 200 --no-pager
```

The device certificate and database live in
`/var/lib/infra-tools/syncthing`. Preserve that directory to retain the
server's device ID. The service uses the Debian Syncthing package and disables
Syncthing's self-updater so normal APT maintenance remains authoritative.

To stop sharing through the managed endpoint, run:

```bash
infra-tools patch fileserver --no-syncthing
```

This stops and removes `infra-syncthing.service` and clears its saved peer and
folder declarations. It deliberately leaves the Syncthing package, synchronized
folder contents, and `/var/lib/infra-tools/syncthing` in place. Re-enabling the
endpoint therefore retains the same server device ID. Delete retained data only
as a separate, deliberate cleanup after verifying that it is no longer needed.

## Boundaries

- Device IDs grant folder-level Syncthing trust, not Unix account access or
  general network access.
- Syncthing has no per-file ACL inside a folder. Use separate folders when
  coworkers need different access.
- Do not synchronize live databases, virtual machine images, Git working trees,
  or application state that requires transactional consistency.
- A compromised authorized device can still replace or delete shared data.
  Keep versioning enabled on the hub and maintain an independent backup.
- A second Syncthing instance using TCP/QUIC 22000 or GUI port 8384 will conflict
  with the managed service. Stop or reconfigure the other instance first.
- This capability is rejected for `server_proxmox`, the root account, and OCI
  targets. Run the hub in a normal Debian VM, LXC, or physical host instead.
