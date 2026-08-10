# Samba Shares

infra_tools configures authenticated Samba 4 file shares on Debian systems.
This document covers initial setup, credentials, access changes, fast updates,
removals, and related SMB client mounts.

## How shares are managed

Each share has an access mode, name, one absolute directory path, and one or
more users:

```text
--share ACCESS_TYPE SHARE_NAME PATH USERS
```

`ACCESS_TYPE` is `read` or `write`. Share names may contain letters, numbers,
dots, underscores, and hyphens, and must be unique in a command. A share has
exactly one directory root (never `/`); use a separate `--share` option for
each directory.

The server creates a Unix user and Samba password for every declared user, then
uses a per-share Unix group. The share's group membership and configuration are
reconciled to the declared state. A later update can therefore remove users as
well as add them.

## Initial setup

The full setup installs and hardens Samba, configures the firewall and
fail2ban, and creates the requested shares:

```bash
infra_tools setup server_lite fileserver admin \
  --samba \
  --share read documents /srv/documents alice,bob \
  --share write dropbox /srv/dropbox alice,carol
```

The target must be Debian and the setup user must have root SSH access. Share
paths are created when needed. Paths below `/mnt` must already be on a mounted
filesystem; this prevents accidentally creating a share on the root disk when
a data drive is missing.

For a NAS with storage maintenance, combine shares with sync and scrub jobs:

```bash
infra_tools setup server_lite fileserver admin \
  --samba \
  --share read media /srv/media guest \
  --sync /srv/documents /srv/backup daily \
  --scrub /srv/backup .pardatabase 5% weekly
```

## Credentials

The safest workflow stores passwords in the mode-0600 workspace credential
store, without putting them in shell history or process arguments:

```bash
infra_tools credentials set alice
infra_tools credentials set bob

infra_tools setup server_lite fileserver admin \
  --samba \
  --share write documents /srv/documents alice,bob
```

The `USERS` value is a comma-separated list. Bare usernames resolve through
the workspace credential store; every bare username must have a saved
credential. Inline `username:password` values are supported for controlled
automation, but the password is visible to local process inspectors:

```bash
infra_tools setup server_lite fileserver admin \
  --samba \
  --share read public /srv/public guest:temporary-password
```

`--credential USERNAME PASSWORD` can save or update a workspace credential as
part of a command. Use it only when the invoking environment is trusted:

```bash
infra_tools setup server_lite fileserver admin \
  --samba \
  --credential alice 'correct horse battery staple' \
  --share write documents /srv/documents alice
```

Passwords are omitted from saved setup state and reconstructed commands. Samba
password changes are supplied to `smbpasswd` over standard input rather than
embedded in a shell command.

## Access modes and permissions

Read shares set `read only = yes` and grant users read/traverse permissions.
Write shares set `read only = no`, add the share group to `write list`, and use
setgid directory permissions so new files inherit the share group:

```bash
# Read-only reference material
infra_tools setup server_lite fileserver admin \
  --samba --share read reference /srv/reference alice,bob

# Collaborative directory
infra_tools setup server_lite fileserver admin \
  --samba --share write projects /srv/projects alice,bob
```

The same share name identifies a logical share. Changing `read` to `write`
replaces the old generated section and group; it does not leave the old access
path active.

## Fast share-only updates

After an initial setup, use `shares` to update Samba without reinstalling
packages, changing the firewall, rebuilding unrelated services, or running the
full setup lifecycle. The host must have a saved setup configuration:

```bash
# Add a new share while preserving the other saved shares
infra_tools shares fileserver \
  --share read archive /srv/archive alice
```

The `--share` option replaces the saved share with the same name. Supply the
complete desired user list when changing membership:

```bash
# Add carol and remove bob from the documents share
infra_tools shares fileserver \
  --share write documents /srv/documents alice,carol
```

Change access mode or path with the same operation:

```bash
# Convert documents from read-only to collaborative write access
infra_tools shares fileserver \
  --share write documents /srv/documents alice,carol
```

Update a user's workspace password while updating a share:

```bash
infra_tools shares fileserver \
  --credential carol 'new-password' \
  --share write documents /srv/documents alice,carol
```

Remove a share by logical name. Its managed Samba section and access group are
removed; unrelated hand-written sections remain untouched:

```bash
infra_tools shares fileserver --remove-share archive
```

Multiple changes can be combined. Each requested share is reconciled and Samba
is reloaded once after the complete candidate configuration passes `testparm`:

```bash
infra_tools shares fileserver \
  --share write documents /srv/documents alice,carol \
  --share read photos /srv/photos bob \
  --remove-share old-media
```

Use `--dry-run` to validate and display the remote operation without making a
connection or changing the saved configuration:

```bash
infra_tools shares fileserver \
  --share read photos /srv/photos bob \
  --dry-run
```

## Security behavior

The generated global Samba configuration:

- requires SMB3 or newer;
- requires signing and encryption;
- disables NetBIOS and exposes TCP 445 only;
- disables guest access and anonymous enumeration; and
- validates candidate `smb.conf` content with `testparm` before reload.

The setup also configures a fail2ban jail for failed Samba authentication. A
share's internal directories identified by configured scrub jobs are hidden
from SMB clients with `veto files`.

## Connecting from a client

The server share name is `<SHARE_NAME>_<ACCESS_TYPE>`:

```bash
# Linux client, read-only share
smbclient //fileserver/documents_read -U alice

# Linux client, interactive mount
sudo mount -t cifs //fileserver/projects_write /mnt/projects \
  -o username=alice,vers=3.0,seal
```

For persistent client mounts managed by infra_tools, use `--mount-smb` on the
client setup. It creates a root-only credential file and a systemd automount:

```bash
infra_tools credentials set alice
infra_tools setup workstation_desktop client admin \
  --mount-smb /mnt/projects fileserver alice projects_write /
```

The mount `CREDENTIALS` field follows the same rule as share users: use a bare
username backed by the workspace credential store, or an inline
`username:password` only in controlled automation.

Managed SMB mountpoints must be distinct, normalized directories below `/mnt`
(for example, `/mnt/projects`). This prevents a mount configuration from
changing ownership of an operating-system path.

## Troubleshooting

Inspect the generated configuration and service state on the server:

```bash
sudo testparm -s /etc/samba/smb.conf
sudo systemctl status smbd
sudo journalctl -u smbd --since '-15 min'
sudo pdbedit -L
```

If a fast update reports that Samba is not installed, run the full setup once
with `--samba`. If a username-only share fails validation, create or update its
workspace credential first:

```bash
infra_tools credentials set alice
infra_tools shares fileserver --share read documents /srv/documents alice
```
