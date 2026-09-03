# Minimal web panel

The optional infra-tools web panel is a small, browser-based dashboard for one
managed machine. It links to detected web services, shows configured SSH, RDP,
and Samba access, displays a sanitized view of current auditd activity, and
offers only maintenance actions supported by software on that machine. It is
not installed unless `--web-panel` is selected.

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

The panel normally runs as the setup user so its supported per-user maintenance
action has the intended identity. For a root-managed setup, infra-tools instead
creates a locked `infra-web-panel` system account with a dedicated primary
group; the browser service never runs as root or as the shared `nobody` account.

### Notification ingest API

An optional API lets other managed machines send their normal infra-tools
notifications to this panel. It is off by default and requires HTTPS:

```bash
infra-tools patch 192.168.1.50 agent \
  --web-panel \
  --ssl \
  --web-panel-notification-ingest
```

The fixed endpoint is `https://HOST/api/v1/notifications`. Enabling it creates
a random bearer token at
`/etc/infra-tools/web-panel/notification-ingest.token`; repeated setup runs
preserve that token. The file is readable only by root and the panel service
account's primary group, not by the shared web-server group. Read it on the
panel host with `sudo` and configure a sending machine with a webhook target
whose URL fragment contains the token:

```bash
infra-tools patch sender.example agent \
  --notify webhook \
  'https://panel.example/api/v1/notifications#TOKEN_FROM_PANEL_HOST'
```

The notification sender removes the fragment from the request URL and sends it
as an `Authorization: Bearer ...` header. The token therefore does not enter
the HTTP request path or Nginx access logs. Treat the complete configured
target as a credential: keep it out of shared command output, and limit access
to the sending machine's saved setup state. To rotate it, remove the token file
on the panel host and rerun setup with the ingest flag, then update every
sender. Use `--no-web-panel-notification-ingest` to disable the endpoint while
keeping the panel. A successful disable first restarts the application without
ingest and removes the public Nginx route, then deletes the bearer token. This
ordering keeps an interrupted setup from breaking an endpoint that is still
running with its previous configuration.

A newly stored event returns HTTP 202 with `duplicate: false`. A repeated event
ID returns HTTP 200 with `duplicate: true`; this acknowledges a delivery retry
without adding another history entry.

Remove the web panel, its htpasswd and ingest-token data, and its bounded event
history with:

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
- when the shared `infra-web` gateway is installed, its web-hosting landing page
  is linked even before any individual sites or forwards have been published;
- live `infra-web` forwards and published static sites are discovered when the
  page loads;
- a compact live overview reports uptime, memory and root-disk use, whether a
  reboot is pending, and the managed automatic-package-update timer state;
- a root-only timer queries the last 24 hours of auditd events every five
  minutes and exports at most 100 structured summaries, including no more than
  25 routine privileged-command entries so integrity changes stay visible. The
  unprivileged panel can read that snapshot but cannot read raw audit logs. The
  snapshot includes
  time, audit category, paths, actors, operations, and executables when auditd
  supplies them; it deliberately excludes raw records, command arguments, and
  `proctitle` data. Before reporting a clean result, the exporter verifies that
  kernel auditing is enabled, auditd is running, and every expected managed
  audit key is loaded. Missing coverage and failed queries appear as specific
  warnings instead of a false clean result. Setup also reloads the managed
  rules on a rerun even when their on-disk file has not changed. A snapshot
  older than 15 minutes is shown as stale and degraded, so a stopped exporter
  cannot leave an old clean result on the dashboard indefinitely;
- when notification ingest is enabled, the latest 100 accepted notifications
  appear with their source system, status, explanation, suggested action, and
  reported occurrence time plus server-recorded receipt address/time. Input
  must be a bounded schema-version-2 notification; unknown fields are
  discarded and malformed or deeply nested input is rejected. New senders
  include a stable event ID, and
  repeated attempts with that ID are acknowledged without adding duplicate
  history entries. A sender-provided system name is descriptive rather than a
  cryptographic identity, so investigations should correlate it with the
  server-recorded source address;
- when the shared gateway uses the machine-local CA, a certificate-trust section
  provides its public download, SHA-256 fingerprint, compact GUI guidance, and
  copy/paste scripts for Debian/Ubuntu, Arch, Fedora/RHEL, macOS, and Windows.
  Every script downloads the certificate into the current (typically
  Downloads) folder and verifies the machine-specific fingerprint before
  changing the trust store. The whole guide and its script collection are
  collapsed until requested. Publicly trusted certificates are identified
  without offering an unnecessary download;
- T3 Code machines receive an **Update to latest** action, which runs T3's
  supported user-service updater and then the managed readiness repair/check.
  During that update, the panel uses infra-tools' short-lived `loginctl` shim
  to confirm lingering is already enabled or scope T3's redundant no-argument
  request to the validated setup user. Service, runtime, endpoint, pairing, and
  managed-skill checks are always required. Git identity is required only when
  one was staged, while GitHub authentication and its credential helper are
  required only when GitHub credentials were staged;
- machines without T3 Code do not receive that action.

The page contains no general command runner, terminal, package form, or
arbitrary service controls. Maintenance actions are fixed server-side
operations. Nginx applies Basic Auth, request throttling with headroom for the
update-status refresh, and a fail2ban jail; the application listens only on a
Unix socket and uses a per-process CSRF token for state-changing forms. The
socket alone is shared with Nginx; the bearer token, audit snapshot, and
notification history are isolated to the panel process's primary group.

The ingest route is the sole Basic Auth exception. It exists only when the flag
is enabled, accepts only `POST`, has a separate lower rate limit and 64 KiB body
limit, requires the generated bearer token using constant-time comparison, and
fails closed unless Nginx reports HTTPS. Accepted records are schema-validated
and retained in a bounded local file. The browser dashboard itself remains
behind Basic Auth.

The panel intentionally does not offer a general package-update button. APT
updates are privileged, can hold package-manager locks for an extended period,
and may require reboot coordination; configured systems already expose their
managed automatic-update schedule in the overview. Use setup with
`--refresh-packages` for a deliberate immediate reconciliation.

## Access and troubleshooting

The final setup or patch summary prints the complete web panel URL. A first setup
without `--web-panel-password` fails rather than creating an unprotected
web panel. On a rerun, an already-valid password file is preserved.

Target-side checks:

```bash
sudo systemctl status infra-tools-web-panel.service
sudo journalctl -u infra-tools-web-panel.service -n 100 --no-pager
sudo systemctl status infra-tools-web-panel-audit.timer
sudo journalctl -u infra-tools-web-panel-audit.service -n 100 --no-pager
sudo nginx -t
```

Repeated failed browser logins are recorded in a privacy-preserving Nginx log
and banned by the `infra-tools-web-panel` fail2ban jail. Passwords and
Authorization headers are not written to that log.
