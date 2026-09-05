# Minimal web panel

The optional web panel is a browser dashboard for one managed machine. It is
not installed unless `--web-panel` is selected.

| Panel area | Shows |
| --- | --- |
| Overview | Uptime, memory, root-disk use, reboot status, and update timer state |
| Services | Configured and discovered web, SSH, RDP, Samba, Gogs, and Antistatic access |
| Audit activity | A sanitized snapshot of current auditd events and collection health |
| Notifications | Events accepted from other machines when ingest is enabled |
| Maintenance | Only fixed actions supported by software on that machine |

## Install the panel

HTTPS is recommended:

```bash
infra-tools setup agent_vm 192.168.1.50 agent \
  --web-panel \
  --web-panel-password 'replace-this-value' \
  --ssl
```

The default port is 80 for HTTP or 443 with `--ssl`. Select another port when
the default belongs to another service:

```bash
infra-tools patch 192.168.1.50 agent \
  --web-panel 9443 \
  --web-panel-password 'replace-this-value' \
  --ssl
```

The final setup summary prints the panel URL.

### Login behavior

- The Basic Auth username is the setup username.
- The password is hashed before upload and is not saved or reconstructed.
- First installation requires `--web-panel-password`.
- A later patch preserves the password when the flag is omitted.
- Repeat the flag to rotate the password.
- If the setup username changes, supply a new password to replace the single
  Basic Auth record.

The panel normally runs as the setup user. A root-managed setup instead uses a
locked `infra-web-panel` service account; the browser service never runs as
root or the shared `nobody` account.

## Notification ingest API

The ingest API lets other machines send normal infra-tools notifications to
the panel. It is behind an explicit flag, disabled by default, and available
only with HTTPS.

### Enable the receiver

```bash
infra-tools patch 192.168.1.50 agent \
  --web-panel \
  --ssl \
  --web-panel-notification-ingest
```

This patch assumes the panel is already installed. For a first installation,
add `--web-panel-notification-ingest` to the setup command above.

| Setting | Value |
| --- | --- |
| Endpoint | Panel URL plus `/api/v1/notifications` |
| Method | `POST` |
| Authentication | Generated bearer token |
| Token file | `/etc/infra-tools/web-panel/notification-ingest.token` |
| Payload | infra-tools notification schema version 2 |
| History | Latest 100 accepted events |

The token is created once and preserved across setup runs. On the panel host:

```bash
sudo cat /etc/infra-tools/web-panel/notification-ingest.token
```

### Add a sender

Use the endpoint as a normal webhook target and put the token in its URL
fragment:

```bash
infra-tools patch sender.example agent \
  --notify webhook \
  'https://panel.example/api/v1/notifications#TOKEN_FROM_PANEL_HOST'
```

The sender converts the fragment to an `Authorization: Bearer ...` header; the
fragment is not sent in the request URL. Open **Notifications** after the
sender's setup completes to verify delivery.

See [Notifications](NOTIFICATIONS.md) for delivery levels, event meaning, the
full payload contract, and retry behavior.

### Operate the receiver

| Task | Action |
| --- | --- |
| Disable ingest | Patch with `--web-panel --ssl --no-web-panel-notification-ingest` |
| Re-enable ingest | Patch with `--web-panel --ssl --web-panel-notification-ingest` |
| Rotate token | Remove the token file on the panel, rerun with the enable flag, then update every sender |
| Remove panel and its data | Patch with `--no-web-panel` |

Token rotation on the panel host:

```bash
sudo rm -- /etc/infra-tools/web-panel/notification-ingest.token
```

Then rerun the enable command and copy the new token to every sender. Disabling
ingest removes its public route and token but keeps the dashboard. Removing the
panel also removes Basic Auth data, notification history, and audit snapshots.

### API behavior and security

| Result | Response |
| --- | --- |
| New event stored | HTTP 202, `duplicate: false` |
| Existing event ID | HTTP 200, `duplicate: true`; no second history entry |
| Invalid token or request | Rejected without storing the event |
| Excess requests or body size | Rejected by the dedicated rate/body limits |

The endpoint:

- is the panel's only Basic Auth exception;
- accepts only `POST` at the fixed standard URL;
- requires HTTPS as reported by the local Nginx proxy;
- compares the bearer token in constant time;
- has a separate rate limit and 64 KiB request-body limit; and
- validates bounded schema-v2 data, discards unknown fields, and rejects
  malformed or deeply nested input.

The token file is readable only by root and the panel service account's primary
group. Treat the fragment-bearing sender target as a credential. A reported
system name is descriptive, not authenticated machine identity; investigations
should also use the panel-recorded source address and receipt time.

## Audit activity

A root-only timer exports a sanitized audit snapshot every five minutes. The
unprivileged panel cannot read raw audit logs.

| Property | Behavior |
| --- | --- |
| Time window | Last 24 hours |
| Maximum entries | 100, including no more than 25 routine privileged commands |
| Included context | Category, time, paths, actors, operations, and executables when available |
| Excluded data | Raw audit records, command arguments, and `proctitle` |
| Health checks | Kernel auditing, auditd service, query result, and loaded managed keys |
| Staleness | Snapshots older than 15 minutes are marked degraded |

Missing coverage and failed queries appear as warnings, not as a clean result.
A rerun reloads managed audit rules even when their on-disk file is unchanged.

## Services and maintenance actions

The panel renders configured access from saved setup state and discovers live
`infra-web` forwards and static sites at page load. When the shared gateway is
installed, its landing page is linked before individual sites are published.

T3 Code machines receive an **Update to latest** action. The action runs the
supported user-service updater and readiness checks for the service, runtime,
endpoint, pairing, and managed skills. Git identity and GitHub authentication
are checked only when those credentials were staged. Machines without T3 Code
do not receive the action.

There is no terminal, arbitrary command runner, package form, or general
service control. There is also no general package-update button; use setup with
`--refresh-packages` for deliberate reconciliation.

## HTTPS and access controls

With `--ssl`, the panel reuses a suitable existing certificate or the shared
per-machine infra-tools CA. See [Client CA trust](CLIENT_CA_TRUST.md) for client
enrollment. Without `--ssl`, Basic Auth crosses the network as plaintext; use
that mode only on a trusted network.

Other controls include:

- Basic Auth on dashboard routes;
- request throttling and an `infra-tools-web-panel` fail2ban jail;
- a Unix-socket-only application listener;
- per-process CSRF tokens for state-changing forms; and
- separate service-group access for the socket, bearer token, audit snapshot,
  and notification history.

The panel supports server and workstation setup families. It is rejected on
`server_proxmox`, which has a separate management-firewall flow.

## Troubleshooting

Run these checks on the panel host:

```bash
sudo systemctl status infra-tools-web-panel.service
sudo journalctl -u infra-tools-web-panel.service -n 100 --no-pager
sudo systemctl status infra-tools-web-panel-audit.timer
sudo journalctl -u infra-tools-web-panel-audit.service -n 100 --no-pager
sudo nginx -t
```

| Symptom | Check |
| --- | --- |
| Panel setup rejects ingest | Include both `--web-panel` and `--ssl` |
| No sender events | Confirm the sender target, delivery level, token, and HTTPS endpoint |
| Audit status is stale | Check the audit timer and audit service journal |
| Login is rejected repeatedly | Check Nginx and the `infra-tools-web-panel` fail2ban jail |
| Private-CA browser warning | Follow [Client CA trust](CLIENT_CA_TRUST.md) |

Failed browser logins are written to a privacy-preserving Nginx log.
Passwords and Authorization headers are not logged.
