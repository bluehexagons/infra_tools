---
name: infra-tools-desktop
description: Use native graphical applications in the VM's shared XRDP desktop, with human handoff. Prefer available T3 Code or Playwright tools for browser testing.
metadata:
  managed-by: infra_tools
---

# Shared native desktop

The setup account owns one XRDP/Xorg desktop on this VM. The human's RDP client
and your commands use the same applications and display. The desktop is created
on demand and persists through RDP or agent disconnection until desktop logout,
failure, or VM shutdown. Only one human RDP connection is supported at a time.

Read `status` for the configured environment (XFCE by default; i3, Cinnamon or
LXQt may be selected), current state and geometry. Discover applications with
`command -v` or package queries; installation of this skill does not imply that
a particular editor or browser exists. Standard emulated graphics use software
rendering; heavy 3D work may be slow and does not establish GPU compatibility.

Use it for native editors, office applications, graphical tools, and behavior
that specifically depends on the desktop environment. Use shell commands for
files, builds, and service operations. For almost all browser testing, prefer
the available T3 Code collaborative browser or managed Playwright tools and
their installed browser-testing skill. Canvas/WebGL testing alone does not
require a desktop. Use desktop browser input only when the task requires its
particular profile/native integration, or browser tools are unavailable or
unsuitable and the reduced coverage is acceptable. Explain that choice.

The desktop browser runs on the VM. It has a separate profile from Playwright
and the client-side T3 browser. Do not copy cookies or assume shared logins.

## Lifecycle and application launch

Run commands as the setup account, without sudo:

```bash
infra-tools desktop status
infra-tools desktop start
infra-tools desktop exec -- thunar /home/agent
```

Use the actual account's paths. `status` only observes; `start` reuses a running
desktop and waits for readiness when initialization is in progress. During
`starting`, geometry may be `null`; inspect any `detail` if startup fails.
`exec` accepts an argument vector, keeps the invoking shell's working directory,
and supplies the session's display, X authority and D-Bus environment.
Do not guess `DISPLAY`, copy authority cookies,
start a second X server, or import GUI variables into the global user manager.
Output is JSON; failures return a nonzero exit code and an `error` field.

## Observe, act, verify

Capture a new private PNG (existing files are never overwritten), then inspect
it using your available image viewer:

```bash
infra-tools desktop screenshot --output /tmp/desktop-check-1.png
```

Use the returned `generation` and `geometry` for input, for example:

```bash
infra-tools desktop input --generation GENERATION --geometry 1280 720 click --x 400 --y 300
infra-tools desktop input --generation GENERATION --geometry 1280 720 text --text 'example'
infra-tools desktop input --generation GENERATION --geometry 1280 720 key --key ctrl+s
```

Coordinates are full-display pixels. Buttons 4–7 scroll; `move` moves the pointer.
Commands acquire a short exclusive control lease. Keep sequences short, inspect
the result, and recapture after reconnect, resize, focus changes or an error.
A successful input response is not proof that the application changed. Stale
session or geometry errors require a fresh screenshot; never retry old clicks.
Desktop automation provides pixels and input, not DOM/network assertions.
Delete temporary screenshots when finished; avoid capturing unrelated user data.

## Human handoff and logout

Before the human takes control, run `infra-tools desktop control pause`. This
revokes agent control while preserving screenshots and human RDP input. Resume
with `infra-tools desktop control resume` when the human hands control back.
Agents must honor pause; it coordinates same-account tools rather than isolating
untrusted code. Ordinary RDP input does not automatically pause agent input.

The human connects with their RDP client using the setup account's Unix password.
They can disconnect and reconnect without ending applications. An SSH tunnel
can reach a loopback-only listener; do not widen network access merely for a test.
Do not save the user's password in agent scripts or command arguments.

Leave the session running after your task unless logout is requested.
`infra-tools desktop logout` asks the desktop to log out; unsaved-work dialogs
may require human action. Confirm `status` becomes stopped. Do not force logout,
kill the user's systemd manager, or restart sesman to recover a failed app.
Explicit start or a new authenticated RDP login creates a fresh session after
logout. Disable RDP-client automatic reconnection when intentionally logging out.
