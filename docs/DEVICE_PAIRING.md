# Protected device pairing

infra-tools can run a small, password-protected enrollment portal for services
that use provider-native device sessions. T3 Code is the first supported
provider. The portal lets a new browser or app obtain its own short-lived,
one-time pairing link without an operator being present in an SSH terminal.

This is deliberately separate from the service being paired:

```text
browser or app
    -> Nginx Basic Auth portal on port 3774
    -> local infra-tools pairing broker
    -> provider's supported pairing command
    -> one-time T3 link for port 3773
    -> provider-native device session
```

Basic Auth protects the ability to issue a link. T3 still authenticates the
resulting connection, owns the per-device session, and provides session
revocation. infra-tools does not create a permanent shared T3 token.

## Configure it

Prepare an Nginx-compatible password file on the controller. This example
prompts without echo and uses the controller's OpenSSL command to create a
SHA-512 crypt hash:

```bash
read -rsp 'Pairing portal password: ' pairing_password
echo
pairing_hash="$(printf '%s\n' "$pairing_password" | openssl passwd -6 -stdin)"
unset pairing_password
umask 077
printf 'agent-admin:%s\n' "$pairing_hash" > /run/secrets/agent-1-pairing.htpasswd
unset pairing_hash
```

Then include device pairing with the T3 Code web service:

```bash
infra-tools setup workstation_dev 192.168.0.41 agent \
  --agent-tool codex --agent-tool opencode \
  --web-interface t3code \
  --web-interface-source 192.168.0.0/24 \
  --device-pairing t3code \
  --device-pairing-auth-file /run/secrets/agent-1-pairing.htpasswd
```

The portal defaults to port `3774`; T3 defaults to `3773`. Override only the
portal with `--device-pairing-port PORT`. The two ports must differ. The portal
inherits the web-interface bind address and source CIDRs, and infra-tools adds
matching managed UFW rules for both ports.

`--interactive` can generate the password file without a pre-existing source.
When T3 Code web setup is selected, choose device enrollment and enter the
portal username and password at the hidden prompts. The password is passed to
OpenSSL over standard input, never as a process argument.

## Enroll a device

From a permitted device, visit:

```text
http://192.168.0.41:3774/
```

Enter the configured Basic Auth username and password, then choose one of the
portal actions:

- **Pair this browser** creates a one-time credential and redirects the current
  browser to T3's pairing page.
- **Create a link for another T3 client** displays the short-lived URL so it
  can be copied into a desktop or mobile T3 Code client.

The broker uses T3's supported `auth pairing create` command with a ten-minute
TTL and JSON output. Pairing URLs are returned only to the authenticated
request. They are not written to setup output, Nginx access logs, the broker
journal, provider configuration, or saved infra-tools commands.

The original SSH-based path remains available:

```bash
infra-tools agent web pair 192.168.0.41 agent
```

It is useful for recovery, for a loopback-only service, or when the pairing
portal was not selected.

## Credentials, reruns, and removal

`--device-pairing-auth-file` is a controller-local, transient secret source.
It must be a regular non-symlink file, no larger than 64 KiB, and not group- or
world-writable. Each non-empty record must use `username:hash` with a
crypt-style hash such as OpenSSL's `$6$...` output. Unsalted `{SHA}` entries
are rejected.

The target copy is root-owned, group-readable by `www-data`, and stored at:

```text
/etc/infra-tools/device-pairing/htpasswd
```

The uploaded source payload is removed after setup succeeds or fails. The
source path and interactive password are excluded from saved configurations.
A normal rerun reuses the installed target file. To rotate portal credentials,
rerun setup or patch with a new `--device-pairing-auth-file`; infra-tools
replaces the file and reloads Nginx only after `nginx -t` succeeds.

To remove enrollment from a saved host:

```bash
infra-tools patch 192.168.0.41 agent --no-device-pairing
```

This disables and removes the broker service, Nginx site, pairing-port firewall
rule, provider definition, and target Basic Auth file. It does not revoke T3
sessions that devices already obtained. Inspect or revoke those with T3's
native access commands:

```bash
t3 auth pairing list
t3 auth session list
t3 auth --help
```

## Security boundary

The portal can mint access to an environment that owns repositories, terminals,
Git credentials, and coding-agent credentials. Treat the portal password as an
administrator credential and use a unique value per VM.

Basic Auth does not encrypt traffic. The direct LAN mode is intended only for a
trusted private network and is always combined with a private/non-global CIDR
allowlist. Anyone who can observe that HTTP traffic can recover the Basic Auth
password and the returned pairing link. For a loopback deployment, forward
both listeners and open `http://127.0.0.1:3774/`:

```bash
ssh -N \
  -L 3773:127.0.0.1:3773 \
  -L 3774:127.0.0.1:3774 \
  agent@192.168.0.41
```

A separately managed trusted HTTPS endpoint is another option, but the current
portal constructs T3 links from the request hostname and configured T3 port;
the proxy must preserve that externally reachable mapping. An HTTPS page such
as `app.t3.codes` cannot connect to the plain HTTP T3 backend because browsers
block mixed content.

The broker listens only on a local Unix socket shared with Nginx. Requests use
a single-use same-site form nonce and are rate-limited per source. Provider
commands are fixed in a root-managed configuration, executed without a shell,
and required to return a link for the expected T3 origin.

## Files and services

```text
infra-tools-t3code.service
infra-tools-device-pairing.service
/etc/nginx/sites-available/infra-tools-device-pairing
/etc/infra-tools/device-pairing/providers.json
/etc/infra-tools/device-pairing/htpasswd
/run/infra-tools-device-pairing/http.sock
```

Check the local components without revealing pairing credentials:

```bash
sudo systemctl status infra-tools-t3code.service infra-tools-device-pairing.service
sudo nginx -t
sudo ss -lntp | grep -E ':(3773|3774)\b'
curl -I http://BIND_ADDRESS:3774/
```

Replace `BIND_ADDRESS` with the configured bind IP (or `127.0.0.1` for a
loopback/all-address bind). The final `curl` should return `401 Unauthorized`
because it omits Basic Auth.
Do not place a portal password or a one-time pairing URL in diagnostics shared
with other people.

## Provider extension contract

The broker is provider-neutral: it loads root-managed provider records with a
fixed command, a public-base-URL flag, JSON result field names, and the public
service port. Adding another provider requires a setup adapter that validates
its supported CLI, writes a safe provider record, and documents its native
session/revocation behavior. Arbitrary operator-supplied commands are not
accepted.

See [T3 Code interfaces](T3_CODE.md) for the complete T3 workflow and
[Credentials and agent configuration](CREDENTIALS.md) for provider and Git
credentials.
