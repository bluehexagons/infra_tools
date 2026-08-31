# Minimal web panel

The optional infra-tools web panel is a small, browser-based dashboard for one
managed machine. It links to detected web services, shows configured SSH, RDP,
and Samba access, and offers only maintenance actions supported by software on
that machine. It is not installed unless `--web-panel` is selected.

## Setup

The flag accepts an optional TCP port. Without a port it uses 80 for HTTP or
443 when `--ssl` is present:

```bash
infra-tools setup agent_vm 192.168.1.50 agent \
  --web-panel \
  --web-panel-password 'replace-this-value' \
  --ssl
```

Use an explicit port when 80 or 443 belongs to another service:

```bash
infra-tools patch 192.168.1.50 agent \
  --web-panel 9443 \
  --web-panel-password 'replace-this-value' \
  --ssl
```

The Basic Auth username is always the setup username. The password flag is
transient: the controller hashes it with SHA-512 crypt before upload, removes
the uploaded payload after setup, and omits it from saved state and
reconstructed commands. A later setup keeps the existing password when the
password flag is omitted. Repeating the flag rotates it. If the setup username
changes, rerun with `--web-panel-password` so the single Basic Auth record
can be replaced with the new username; infra-tools refuses to preserve a
record for a different account.

Remove the web panel and its htpasswd data with:

```bash
infra-tools patch 192.168.1.50 agent --no-web-panel
```

## HTTPS and trust

With `--ssl`, the web panel reuses the certificate selected by the shared internal
web host. If an existing Let's Encrypt certificate covers the machine name it
is reused. Otherwise infra-tools issues the web panel certificate from the same
per-machine CA used by `infra-web`, T3 Code HTTPS forwarding, static sites, and
Godot exports. A client therefore enrolls one CA per machine rather than one
certificate per service. See [Client CA trust](CLIENT_CA_TRUST.md).

Without `--ssl`, Basic Auth is sent over plaintext HTTP. Keep that mode on a
trusted network only; HTTPS is recommended whenever credentials cross a
network.

The web panel is supported by the server and workstation setup families. It is
intentionally rejected on `server_proxmox`: that host uses a dedicated
management-firewall flow and should not gain another administrative web
surface implicitly.

## What appears in the web panel

The configured machine determines the contents:

- configured Gogs, Antistatic, RDP, SSH, and Samba access is rendered from the
  saved setup;
- live `infra-web` forwards and published static sites are discovered when the
  page loads;
- T3 Code machines receive an **Update to latest** action, which runs T3's
  supported user-service updater and then the managed readiness repair/check;
- machines without T3 Code do not receive that action.

The page contains no general command runner, terminal, package form, or
arbitrary service controls. Maintenance actions are fixed server-side
operations. Nginx applies Basic Auth, request throttling, and a fail2ban jail;
the application listens only on a Unix socket and uses a per-process CSRF
token for state-changing forms.

## Access and troubleshooting

The final setup or patch summary prints the complete web panel URL. A first setup
without `--web-panel-password` fails rather than creating an unprotected
web panel. On a rerun, an already-valid password file is preserved.

Target-side checks:

```bash
sudo systemctl status infra-tools-web-panel.service
sudo journalctl -u infra-tools-web-panel.service -n 100 --no-pager
sudo nginx -t
```

Repeated failed browser logins are recorded in a privacy-preserving Nginx log
and banned by the `infra-tools-web-panel` fail2ban jail. Passwords and
Authorization headers are not written to that log.
