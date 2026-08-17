# XRDP configuration and troubleshooting

`infra-tools` configures XRDP for secure, reconnectable desktop sessions with
dynamic resolution. The supported path uses Xorg with `xorgxrdp`; it does not
use Xvnc or a Proxmox emulated display as the RDP display.

## Defaults

| Setting | Default |
| --- | --- |
| Backend | Xorg with the `xrdpdev` driver |
| Rendering | Software rendering with a software cursor |
| Desktop | XFCE is the recommended RDP desktop |
| Listener | All IPv4 addresses on TCP 3389 |
| Firewall | Globally rate-limited access unless `--rdp-source` is supplied |
| Sessions | Ten concurrent sessions |
| Disconnected sessions | Retained indefinitely |
| Idle sessions | Not disconnected automatically |
| Clipboard | Enabled |
| Drive, printer, device, audio, RemoteApp, and video redirection | Disabled |

The session keeps `drdynvc` for dynamic resizing and `cliprdr` for clipboard
support. Use the CLI flags below to change the managed channel policy.

## Set up XRDP

For a remote target, provide the Unix account password through a secret source:

```bash
infra-tools setup workstation_dev 10.0.0.25 agent \
  --desktop xfce --rdp --password "$RDP_PASSWORD" \
  --rdp-source 10.0.0.0/24
```

For local setup of an existing non-root desktop account, reuse its password
without placing it in process arguments:

```bash
sudo "$(command -v infra-tools)" setup workstation_dev localhost "$USER" \
  --control-plane --desktop xfce --rdp --rdp-existing-password
```

`--rdp-existing-password` is local-only. It cannot be combined with
`--password`, does not create or change the account password, and is rejected
when the account does not already exist.

Restrict access to every network that should connect:

```bash
--rdp-source 10.0.0.0/24 --rdp-source 100.64.0.0/10
```

Without `--rdp-source`, XRDP remains reachable through the globally
rate-limited rule. Use `--rdp-bind-address IP` to bind the listener to one
local address. The firewall reconciles only rules tagged `infra_tools RDP` and
does not remove unrelated UFW rules.

Session and channel controls:

```bash
--rdp-max-sessions 3
--rdp-idle-timeout 3600
--rdp-kill-disconnected --rdp-disconnected-timeout 86400
--no-rdp-clipboard
--rdp-drive-redirection
--rdp-audio
```

Ending a disconnected session also ends agents running only inside that
session. Keep durable work in `tmux` or a supervised service before enabling
disconnected-session cleanup.

## Managed configuration

| File | Purpose |
| --- | --- |
| `/etc/xrdp/sesman.ini` | Session manager and Xorg backend |
| `/etc/xrdp/xrdp.ini` | RDP protocol and channel settings |
| `/etc/X11/xrdp/xorg.conf` | Software-rendered `xrdpdev` display |
| `/etc/X11/Xwrapper.config` | X server permissions |
| `~/startwm.sh` | Desktop session startup |

The Xwrapper configuration requires:

```ini
allowed_users=anybody
needs_root_rights=no
```

Because the X server runs without root privileges, `sesman.ini` selects its
configuration as `xrdp/xorg.conf`. Xorg resolves that trusted relative path to
`/etc/X11/xrdp/xorg.conf`; an absolute `-config` path is rejected for a
non-root session and produces the generic "X server could not be started"
login failure.

The startup script sets `XRDP_SESSION=1` and `XRDP_SOCKET=/tmp/xrdp`, disables
screen blanking and DPMS, and starts the selected desktop through D-Bus. XFCE
display profiles and power-management settings that conflict with dynamic
resolution are cleared, while `xfsettingsd` remains enabled for normal desktop
settings.

Existing managed configuration files are saved with a `.bak` suffix before the
managed versions are written. Use the normal setup or patch flow to reapply
them.

## TLS certificate health

XRDP uses `/etc/xrdp/cert.pem` and `/etc/xrdp/key.pem`. Setup verifies that:

- both paths are regular files;
- the private key is readable only by its owner and permitted group;
- OpenSSL can parse the certificate and key;
- the certificate and key match;
- the certificate is not expired; and
- the `xrdp` daemon can read both files.

An invalid pair stops setup and keeps XRDP fail-closed. Expiry within 30 days
generates a warning. The security monitor repeats these checks every 15 minutes
and reports errors, recovery, expiry warnings, or certificate fingerprint
changes once per state change. It never records private-key contents.

Inspect the certificate and daemon access without printing the private key:

```bash
sudo openssl x509 -in /etc/xrdp/cert.pem \
  -noout -subject -issuer -dates -fingerprint -sha256
sudo runuser -u xrdp -- test -r /etc/xrdp/cert.pem
sudo runuser -u xrdp -- test -r /etc/xrdp/key.pem
sudo systemctl status security-monitor.service --no-pager
```

The default certificate is normally self-signed. Certificate validity does
not make it trusted by RDP clients; use an operator-managed certificate when
client trust is required.

## Proxmox and containers

A hosted desktop VM receives a VirtIO-GPU recovery/noVNC console and a serial
socket. XRDP starts a separate software-rendered Xorg display, so changing the
Proxmox emulated graphics device does not accelerate the RDP session. Setup
does not add the desktop user to the `video` or `render` groups for this path.

Unprivileged Proxmox LXC guests support basic XRDP access, but host limits may
affect desktop polish. A VM is the better choice for a reproducible graphical
workstation. See [Machine types](MACHINE_TYPES.md) and
[Proxmox workflows](PROXMOX.md) for capability and provisioning details.

## Troubleshooting

### Check the service and configuration

```bash
sudo systemctl status xrdp xrdp-sesman --no-pager
sudo xrdp --version
sudo grep -A 5 '\[Xorg\]' /etc/xrdp/sesman.ini
sudo cat /etc/X11/Xwrapper.config
```

The Xwrapper output should contain `allowed_users=anybody` and
`needs_root_rights=no`. Confirm that the Xorg backend uses `xrdpdev`, not
Xvnc.

### Inspect logs

```bash
sudo journalctl -u xrdp -u xrdp-sesman -n 100 --no-pager
sudo tail -100 /var/log/xrdp.log
sudo tail -100 /var/log/xrdp-sesman.log
tail -100 ~/.xsession-errors
tail -100 ~/.xorgxrdp.*.log
```

### Black screen or immediate disconnect

Check the Xwrapper settings, then confirm that the desktop and D-Bus startup
commands are installed. Look for permission errors in `xrdp-sesman.log` and
startup failures in `~/.xsession-errors`. A stale desktop autostart entry or
fixed XFCE display profile can also prevent a session from starting; rerun
`patch` to restore the managed desktop settings.

If the connection log reports that `ip` is not needed, reapply the current
configuration. Older managed `xrdp.ini` files included an obsolete `ip` field
in the local Xorg session entry. The warning itself is harmless, but the same
older configuration may also contain an absolute Xorg `-config` path that
prevents a non-root X server from starting.

### Freeze while resizing

Try a fixed client resolution first. If that works, resize more slowly and
test another RDP client. Confirm that the session uses `xrdpdev`, that
`xfsettingsd` is running, and that no stale XFCE display profile is overriding
RANDR. If the freeze persists, capture the XRDP, Xorg, and session logs while
reproducing it.

For a minimal diagnostic session, temporarily replace the command in
`~/startwm.sh` with `exec xterm`, reconnect, and restore the managed script
after testing. An xterm session that remains stable points to the desktop
configuration rather than XRDP transport.

### Verify a live session

```bash
ps aux | grep -E 'xrdp|Xorg|xfce4-session|dbus-daemon'
xrandr
```

An active session should include an Xorg process using `xrdpdev`,
`xrdp-sesman`, and the selected desktop session. When reporting a problem,
include the XRDP and xorgxrdp versions, client and desktop versions, the
relevant log excerpts, and whether reconnecting changes the result.
