# Managed Syncthing

The Syncthing integration provides private, bidirectional file exchange for a
known group without requiring a VPN or a publicly reachable server. Syncthing
encrypts device-to-device traffic and can use outbound relays when direct
connections are unavailable.

Infra-tools owns the service boundary: a non-root systemd service, an
authenticated HTTPS admin endpoint, a fixed writable root at `/srv/syncthing`,
and conservative network defaults. The Syncthing web GUI owns devices, folders,
folder direction, and versioning. Rerunning infra-tools preserves those GUI
changes.

## Install the endpoint

Save the web administrator password in the workspace credential store, then
enable Syncthing:

```bash
infra-tools credentials set syncthing-admin
infra-tools setup server_lite fileserver admin --syncthing
```

The credential command prompts without exposing the password in shell history.
Setup prints the server device ID and an HTTPS admin URL. The default login
username is `syncthing-admin`; choose a different workspace credential name
with `--syncthing-admin USERNAME`:

```bash
infra-tools credentials set file-admin
infra-tools setup server_lite fileserver admin \
  --syncthing --syncthing-admin file-admin
```

The HTTPS listener uses the existing infra-tools web gateway, certificate, and
access-source policy. If the server uses its local CA, enroll that public CA on
each administrator's browser device as described in
[Internal HTTPS sites and previews](INTERNAL_WEB.md#certificate-trust). Do not
disable certificate verification.

## Add people and folders

1. Open the printed HTTPS URL and sign in.
2. Have each coworker install Syncthing and send you their device ID.
3. In the server GUI, select **Add Remote Device**, enter the ID and a helpful
   name, and save it. Do not mark a coworker as an introducer.
4. Select **Add Folder**, use a path below `/srv/syncthing`, and select only the
   devices that should receive it.
5. On each coworker's client, add the server device ID and accept the offered
   folder at an appropriate local path.

Coworkers need only the Syncthing client. They do not need the admin URL, its
password, SSH access, a VPN, or access to one another's devices. A normal
**Send & Receive** folder is bidirectional. Use separate folders for groups
that need different access, because Syncthing does not provide per-file ACLs
inside one folder.

New folders default to `/srv/syncthing` and staggered versioning for up to one
year. Both are visible and adjustable in the GUI. Existing folder settings are
never reset by an infra-tools rerun. Versioning is useful recovery but is not
an independent backup; retain server snapshots or another backup for disk
loss, administrator mistakes, or compromise.

## Administrator credential rotation

Replace the stored credential and reconcile the saved setup:

```bash
infra-tools credentials set syncthing-admin
infra-tools patch fileserver --syncthing
```

Use the custom username instead when `--syncthing-admin` was selected. Setup
resets the web login from that workspace credential but preserves the server's
device identity, remote devices, folders, and their settings. For a routine
membership or folder change, use the GUI only; no setup rerun is needed.

## Service operations and removal

```bash
sudo systemctl status infra-syncthing.service
sudo journalctl -u infra-syncthing.service -n 200 --no-pager
```

The device certificate and database live in
`/var/lib/infra-tools/syncthing`. Preserve that directory to retain the server
device ID. The Debian package remains authoritative, and Syncthing's
self-updater is disabled.

To remove the service and HTTPS route while preserving state and files:

```bash
infra-tools patch fileserver --no-syncthing
```

Re-enabling the endpoint retains the device ID and GUI-managed sharing state.
Delete `/var/lib/infra-tools/syncthing` or `/srv/syncthing` only as a separate,
deliberate cleanup after verifying the data is no longer needed.

## Security boundaries

- The GUI remains bound to `127.0.0.1:8384`; only the managed HTTPS gateway is
  externally reachable, and its firewall scope follows infra-tools access
  sources.
- The service can write only its state directory and `/srv/syncthing`; GUI
  folder paths outside that root will fail rather than expanding access.
- Automatic router mapping is disabled. Existing routing can permit direct
  device connections; otherwise outbound relay fallback remains enabled.
- Device IDs grant folder-level Syncthing trust, not Unix or general network
  access. A compromised authorized device can still replace or delete shared
  data.
- Do not synchronize live databases, virtual-machine images, or application
  state that requires transactional consistency.
- A second Syncthing instance using TCP/QUIC 22000 or GUI port 8384 conflicts
  with the managed service.
- This capability is rejected for `server_proxmox`, the root account, and OCI
  targets. Use a normal Debian VM, LXC, workstation, or physical server.
