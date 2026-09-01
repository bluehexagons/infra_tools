---
name: infra-tools-browser-testing
description: Browser-test web applications on an infra-tools agent VM that has both T3 Code collaborative previews and managed VM-local Playwright.
metadata:
  managed-by: infra_tools
---

# T3 preview and Playwright

This VM has two browser surfaces with different strengths and network origins.
Choose deliberately; T3 preview is not a mandatory first step when collaboration
is not part of the task.

## Choose the browser

Prefer VM-local Playwright when the task needs repeatable headless interactions,
DOM/console/network inspection, loopback access, canvas input, or browser-engine
verification that does not need to be shared live with the user. It remains
available when the T3 application is closed.

Prefer the T3 collaborative preview when the user should watch or participate,
the requested evidence must appear in the shared UI, or the task specifically
tests the connected client's routes or certificate trust. That browser runs in
the connected client's context, not the VM's.

When either surface is equally suitable, an already attached preview is useful
for collaboration. Otherwise Playwright is the dependable default. State which
surface and network origin produced the result when that distinction matters.

## Use managed Playwright

Before the first VM-local browser action, run:

```bash
infra-tools agent doctor --capability browser --json
```

Use Playwright only when `healthy` is true. Follow the stable `issues` and
`remediation` fields when it is not; do not install another browser stack or
mutate the managed launcher. `stale_processes` requires restarting the affected
agent session.

Keep development servers on loopback. Playwright originates on the VM, so it
can reach VM loopback and uses the VM's DNS, routes, source IP, and trust store.
Generated evidence belongs in the private, bounded
`~/.local/state/infra_tools/playwright-mcp` directory by default. Omit
`filename` unless the user requested a workspace deliverable.

For canvas applications, map controls from a screenshot and use the bounded
coordinate input tool. Coordinates are viewport-relative CSS pixels; recapture
after resizing. The launcher waits one second after actions. For a still-empty
WebGL capture, wait another second and retry once. Browser-process `ReadPixels`
warnings are not page console errors.

## Use the collaborative preview

Call `preview_status` first. If there is no automation-capable tab, call
`preview_open` once. Do not repeatedly reopen or poll: the T3 application may
simply be closed or minimized. A hidden tab may still accept navigation while
snapshot or recording capture is unavailable; attempt one snapshot before
classifying coverage.

`available: true` with `tabId: null` means the automation host is attached but
this agent session has no current tab. Call `preview_open` once; do not report
the collaborative browser as unavailable from that status alone. Preserve the
returned `tabId` for later actions instead of relying on an implicit current
tab after an agent-session boundary.

Preview absence is a normal fallback condition. Continue immediately with
healthy Playwright when VM-origin testing fits the task. Do not treat the
closed T3 application as an application failure.

An `environment-port` target rewrites the port onto the environment connection
host; it is not a tunnel to VM loopback. If a verified loopback server leaves
the preview at `about:blank` with no network entry, use Playwright for VM-origin
coverage. Publish through the managed `infra-tools-web-gateway` only when
client-visible access is itself in scope; do not rebind the server or widen the
firewall solely for automation.

Opening a tab or seeing the requested URL in status is not proof of rendering.
Confirm visible content or a snapshot. For WebAssembly/WebGL, allow one bounded
startup interval beyond document load before judging the application frame.

Take a snapshot before interaction and prefer its semantic role/name locators
over coordinates or CSS selectors. Treat a successful input helper response as
dispatch evidence, not proof of the application outcome: follow it with a
bounded `preview_wait_for`, snapshot, or read-only state check. If a keyboard
helper produces no expected state change, use the equivalent semantic click
when the task permits and report the keyboard path as unverified. Do not mutate
the page with evaluation merely to manufacture a passing result.

Viewport presets exercise CSS layout breakpoints without changing the desktop
browser user agent. Snapshot again after resize or scroll because coordinates
and element visibility change, and note that the scroll position can persist
across a resize. Use appearance emulation for light/dark checks, then restore
`system` unless the task needs the override left in place.

Start a recording only when video evidence is useful and always stop it. The
returned recording path belongs to the connected client's artifact store, not
the VM filesystem, so use the returned artifact metadata/link rather than
trying to copy that path from the VM. Keep credentials and unrelated user data
out of recordings. A snapshot action timeline can show the snapshot currently
being assembled as `running`; once the snapshot response returns, judge prior
actions and the returned page state instead of treating that self-entry as a
hung action.

If `preview_open` reports a tab but no preview surface appears, status remains
`visible: false`, and a snapshot fails, do not create more tabs. Confirm the T3
application is open, retry the same tab once, and use a read-only page check
only when it helps distinguish a working background renderer from a failed
navigation. Background DOM access with no mounted UI and repeated snapshot
failure indicates stale T3 preview-presentation state, not an application,
route, certificate, or Playwright failure.

Restarting the desktop client may leave that state in the VM-side T3 service.
Use healthy Playwright while collaboration is optional. If client-visible
coverage is required and the user explicitly accepts interruption of every
active T3 session, restart the managed server as the target user:

```bash
systemctl --user restart t3code.service
```

Reconnect the client, then run status and open once against the new attachment.
Never restart the service silently, repeatedly, or merely because a preview is
closed; a full VM reboot is not the first recovery step.

## Certificate errors are optional to repair

Only treat an explicit `net::ERR_CERT_AUTHORITY_INVALID` preview network entry
as a client trust error. Do not require the user to enroll the VM CA to finish
an otherwise testable task. Route browser work to healthy VM-local Playwright,
continue server and HTTP checks, and report that collaborative client-origin
coverage was skipped. Never use `curl -k`, ignore HTTPS errors, or weaken TLS.

For a managed `infra-web` URL, if the user wants collaborative preview access
restored, run:

```bash
infra-web ca
```

Give the user the reported enrollment URL and SHA-256 fingerprint. If the
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
- ChromeOS: import the verified certificate under certificate-manager
  **Authorities**; managed devices require an authorized administrator.
- Android: use the device's CA certificate installation settings; embedded apps
  may still reject user-added roots.
- iPhone/iPad: install the transferred profile, then enable it under **Settings
  > General > About > Certificate Trust Settings**.

Installing a CA changes client security state, so the user performs that step.
Restart T3 Code after enrollment, recheck preview status, and retry the existing
tab. If they decline, keep using Playwright or skip the affected preview-only
operation.

For a certificate error on any other HTTPS origin, use that origin's documented
trust process or leave the client-origin check skipped; `infra-web ca` does not
repair unrelated certificates.

## Evidence and safety

Test the application- or gateway-reported URL, not a guessed port. Capture only
the interactions, console failures, and screenshots needed for the handoff.
Avoid passwords, tokens, private response bodies, and unrelated user data.
Never infer that client-preview failure means a VM service is down; report the
origin that passed and the origin that could not be exercised.
