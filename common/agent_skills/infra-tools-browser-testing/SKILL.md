---
name: infra-tools-browser-testing
description: Browser-test web applications on an infra-tools agent VM with a collaborative T3 preview or the optional managed Playwright fallback.
metadata:
  managed-by: infra_tools
---

# Browser testing on an agent VM

## Choose the browser path

Prefer the collaborative T3 preview when it is attached to the current
session. It keeps navigation, interaction, screenshots, and failures visible
to the connected user. That browser runs in the connected client's network and
trust context; it does not necessarily share the agent VM's routes, source IP,
DNS, or certificate store.

For an SSH-only session, verify the optional VM-local browser before relying on
it:

```bash
infra-tools agent doctor --capability browser --json
```

Use the stable `issues` list to identify every failed layer and the primary
`remediation` code to choose the managed recovery path. Do not infer repair
steps from a generic unhealthy flag when those fields are present.
`stale_processes` means setup repaired the launcher while an older agent
session kept its previous MCP process; restart the affected agent session
before collecting more evidence.

Use the managed browser integration only when that check succeeds. A missing
capability is expected unless setup requested `--browser-automation
playwright`; report the missing capability instead of installing an unrelated
browser stack or exposing a browser service.

If the doctor reports a complete installation with stale managed launcher
defaults, rerun the saved agent setup. Existing launchers reconcile even when
the browser option is not restated; an explicitly disabled capability does not.
If the installation is incomplete, rerun setup with
`--browser-automation playwright` and its compatible agent selection.

If `preview_status` or `preview_open` reports that no preview automation host
is available, treat that as a handoff rather than an application failure and
run the browser capability doctor above. State explicitly that the fallback is
VM-origin testing when it succeeds.

## Test a project

Keep development servers on loopback. For an external HTTPS URL, publish the
static build or expose the loopback server with the `infra-tools-web-gateway`
skill when that capability is installed.

Test the URL reported by the application or `infra-web`, not a guessed port.
Capture a small set of user-visible interactions, console failures, and a
screenshot when it helps the handoff. Avoid recording passwords, tokens,
private response bodies, or unrelated user data.

For a canvas, map controls from a screenshot and use the managed
`browser_mouse_click_xy` vision tool. It is a bounded coordinate input tool;
do not use an unsafe code-evaluation tool merely to call `page.mouse`. Canvas
coordinates are viewport-relative CSS pixels, so recapture after resizing.

The managed launcher gives actions one second to settle before the next tool
call. If a WebGL screenshot is still black or partially rendered immediately
after input or animation, wait another second and retry once. Verify page
errors with the console tool: Chromium `ReadPixels` messages emitted during
capture are browser-process warnings, not page console errors.

Opening a collaborative tab or seeing the requested URL in preview status is
not proof that the page loaded. Confirm rendered text or a snapshot. A hidden
preview (`visible: false`) can still be automation-capable; visibility and
network reachability are separate.

## Private URLs and network origin

An `infra-web` URL commonly uses an RFC1918 address such as `192.168.x.x`.
The agent VM may reach that address while a collaborative preview on a remote
client cannot, or the gateway's access-source policy may allow one source and
not the other. If navigation, snapshots, or evaluation repeatedly fail for a
private URL:

1. Verify the exact reported URL from the VM without bypassing TLS. For a
   static publication, run `infra-web site doctor NAME` and request one
   non-sensitive changed artifact directly; for a live service, check the
   documented loopback and HTTPS health layers.
2. Distinguish an explicit certificate error from a timeout, unreachable host,
   or empty client result. Do not treat every collaborative-preview failure as
   a certificate problem or an application failure.
3. If VM checks pass but the client cannot load the URL, report the client/VM
   network boundary. Do not broaden UFW/source policy, bind a service to
   `0.0.0.0`, publish it to the internet, or disable TLS merely to make browser
   automation succeed.
4. When a browser-engine check is still required and the current agent
   integration permits the managed fallback, use VM-local Playwright only
   after the browser capability doctor succeeds. Its traffic originates from
   the VM, so it tests a different network path than the collaborative client.

For hash-router URLs, remember that the fragment after `#` never reaches the
server. Server-side checks should request the site root or actual asset; the
browser check should navigate to the complete fragment URL.

The managed Playwright fallback keeps generated evidence in the private,
bounded `~/.local/state/infra_tools/playwright-mcp` directory rather than the
current repository. Omit `filename` for routine evidence; the returned result
links to the resolved private artifact. Playwright treats an explicit
`filename` as a workspace deliverable, so name one only when the user requested
an artifact that belongs with the task deliverables.

## HTTPS trust

Never bypass TLS verification. VM-local Playwright and Chromium use the CA
trust enrolled by setup. A collaborative preview may run on the connected
client and therefore use a different trust store. For a URL published by the
managed `infra-web` gateway, run the following only when that client reports a
certificate error, not for a generic timeout or private-route failure:

```bash
infra-web ca
```

Use its enrollment URL and fingerprint on the client. If VM-local automation
fails trust instead, report the failed capability. Rerun the saved setup to
repair the managed VM trust store only when the task includes that repair.
For any other HTTPS origin, follow that origin's documented trust process.
