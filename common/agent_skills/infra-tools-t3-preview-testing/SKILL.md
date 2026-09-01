---
name: infra-tools-t3-preview-testing
description: Browser-test web applications with T3 Code's collaborative preview on an infra-tools agent VM where managed Playwright is not provisioned.
metadata:
  managed-by: infra_tools
---

# T3 collaborative preview testing

This VM has T3 Code preview guidance but no managed Playwright fallback. The
preview depends on the connected T3 application remaining open and uses that
client's routes and certificate trust.

## Preview availability

Call `preview_status` first. If no automation-capable tab is attached, call
`preview_open` once. Do not repeatedly reopen or poll. A closed or minimized T3
application is a normal coverage limitation, not evidence that the web
application is unhealthy.

When the preview is unavailable, continue with build, unit, service, loopback
HTTP, and managed gateway checks. Report which collaborative browser behavior
was not exercised. Do not install Playwright ad hoc, bind a service to
`0.0.0.0`, or widen firewall policy to manufacture browser coverage.

A hidden tab may still navigate while raster capture is unavailable. Attempt
one snapshot after navigation. If it fails while the tab remains hidden, stop
retrying and continue with non-browser checks. Opening a tab or seeing a URL in
status does not prove the page rendered; confirm visible content or a snapshot.

If `preview_open` reports success but the user sees no preview surface, status
stays `visible: false`, and snapshot capture fails, reuse the same tab for at
most one confirmation. A read-only page check may show that a background
renderer works even though T3 did not mount its UI. Treat that combination as
stale preview-presentation state rather than an application, route, or TLS
failure, and do not create replacement tabs.

Restarting only the desktop client may preserve VM-side preview state. When
collaborative coverage is required and the user explicitly accepts interruption
of every active T3 session, restart the managed server as the target user:

```bash
systemctl --user restart t3code.service
```

Reconnect the client and try status/open once. Never restart the service
silently or for ordinary preview absence. Without approval, leave the browser
operation skipped; a full VM reboot is not the first recovery step.

## Network origin

The preview runs in the connected client's context, not on the VM. An
`environment-port` target rewrites the requested port onto the environment
connection host; it does not tunnel to VM loopback. If the VM endpoint is
healthy but preview navigation remains at `about:blank` with no network entry,
report the client/VM routing boundary.

Use the managed `infra-tools-web-gateway` only when client-visible access is in
scope. Do not rebind the development server or weaken access policy solely to
make preview automation work.

For WebAssembly or WebGL applications, allow one bounded startup interval after
document load before judging the frame. Capture only the interactions, console
failures, and screenshots needed for the handoff; avoid credentials and private
response data.

## Certificate errors are not blockers

Only an explicit preview network error of
`net::ERR_CERT_AUTHORITY_INVALID` establishes a client trust problem. Do not
require the user to trust the VM CA. Skip the affected preview-only operation,
continue server and HTTPS checks from the VM without bypassing verification,
and report the browser coverage gap. Never use `curl -k`, ignore HTTPS errors,
or disable TLS.

For a managed `infra-web` URL, if the user wants to restore collaborative
preview access, run:

```bash
infra-web ca
```

Give them the reported enrollment URL and SHA-256 fingerprint. If the
untrusted URL cannot download its own CA, transfer only the public certificate
over an existing trusted path:

```bash
scp USER@VM:/srv/infra-tools/web/infra-tools-ca.crt .
```

Never transfer the CA private key. Have the user verify the file with
`sha256sum infra-tools-ca.crt` on Linux or
`(Get-FileHash .\infra-tools-ca.crt -Algorithm SHA256).Hash` on Windows, then
give only the matching platform step:

- Debian-based Linux: place the verified `.crt` in
  `/usr/local/share/ca-certificates/` and run `sudo update-ca-certificates`.
- Arch-based Linux: run `sudo trust anchor infra-tools-ca.crt` and
  `sudo update-ca-trust`.
- Fedora/RHEL-based Linux: place it in
  `/etc/pki/ca-trust/source/anchors/` and run `sudo update-ca-trust extract`.
- macOS: import it into the System keychain with Keychain Access, open the
  certificate, and set **Trust** to **Always Trust**.
- Windows current user: run
  `certutil -user -addstore -f Root .\infra-tools-ca.crt`.
- ChromeOS: import it under certificate-manager **Authorities**; managed
  devices require an authorized administrator.
- Android: use the CA certificate installation settings; an embedded app may
  still reject a user-added root.
- iPhone/iPad: install the transferred profile, then enable it under **Settings
  > General > About > Certificate Trust Settings**.

The user performs this client security change. After enrollment, restart T3
Code, recheck status, and retry the existing tab. If the user declines, leave
the preview test skipped and finish with the remaining evidence.

For a certificate error on any other HTTPS origin, use that origin's documented
trust process or leave the client-origin check skipped; `infra-web ca` does not
repair unrelated certificates.
