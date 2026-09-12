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

Use `desktop open /absolute/document` to use its default native application,
or add `--reveal` to open the parent directory. For launch readiness:

```bash
infra-tools desktop exec --wait-window Mousepad --timeout 15 -- mousepad
infra-tools desktop wait --title Mousepad --condition visible --timeout 15
infra-tools desktop launch-status LAUNCH --generation GENERATION
```

Launch results include a session-local `launch` token and PID. Only the latest
128 launches are tracked. A title match can be an existing application window;
inspect returned PID/class and `existing_window_ids` before acting. A running
process or visible window does not prove document readiness. A launcher may exit
successfully after asking an existing process to open a document. On timeout,
inspect before retrying; never automatically launch a duplicate application.

## Observe, act, verify

Capture a new private PNG (existing files are never overwritten), then inspect
it using your available image viewer:

```bash
infra-tools desktop screenshot --output /tmp/desktop-check-1.png
```

Omit `--output` to retain a unique capture in private `~/Pictures/infra-tools/`.
The response includes its absolute path and `captured_at` timestamp. No automatic
cleanup removes response artifacts; delete disposable captures yourself.

Prefer an application screenshot when the result concerns one application:

```bash
infra-tools desktop windows
infra-tools desktop screenshot --window 0x123456 --output /tmp/application-check-1.png
infra-tools desktop screenshot --active-window --output /tmp/active-application-1.png
```

Use a current ID from `windows`; do not guess IDs or select by an ambiguous title.
Window capture excludes window-manager decorations and does not raise or focus
the application. Minimized/hidden windows must be made visible first; failures
never fall back to capturing the whole desktop. Inspect the image for occlusion,
dialogs and unrelated private content before sharing. These are pixel captures,
not exports of off-screen or minimized application content.

`image_geometry` describes the PNG dimensions; top-level `geometry` remains the
full desktop size used by input commands. For window images, `window.origin`
gives the client area's desktop offset. Windows can move without changing the
session generation: recapture the full desktop before coordinate-based input.

When an image helps explain a result, include the inspected screenshot using
the response client's image/attachment support, with a brief caption. A local
image viewer tool lets you inspect it but may not attach it to the final answer.
For clients supporting local Markdown images, use `![caption](/absolute/path.png)`;
otherwise use their artifact/upload tool, or provide a file link and state the
limitation. Keep shared artifacts at stable paths outside Git (or ignored artifact
directories), retain them for the user, and never publish them to an external host
merely to display them. Prefer the narrowest useful capture; do not include
passwords, tokens, or unrelated private windows in evidence.

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
Delete disposable captures when finished; retain screenshots linked in responses.

## Window operations and short sequences

`windows` returns PID/class when available, active window, and an `identity`.
Use the current identity and generation to target an application:

```bash
infra-tools desktop window focus --window WINDOW --identity IDENTITY --generation GENERATION
infra-tools desktop window resize --window WINDOW --identity IDENTITY --generation GENERATION --width 800 --height 600
infra-tools desktop wait --window WINDOW --generation GENERATION --condition active
```

Other operations are `move --x X --y Y`, `maximize`, `minimize`, `restore`, and
`close`. Title changes invalidate the identity; list again. Desktop and panel
windows are excluded from these mutations. This fingerprint reduces stale
targeting but cannot guarantee an X window ID has never been reused.
Operations report requests, not completion: verify their result. `close` asks
the window manager to close normally; an unsaved-work dialog can cancel it.
Use `wait --condition absent` afterward, and inspect dialogs on timeout.
Wait selectors combine window ID, literal title substring, and PID with AND.
Waits release control between observations and remain usable during human pause.

For a brief, already-observed interaction, `desktop sequence /absolute/steps.json
--generation GENERATION` accepts 1–20 JSON action objects (`input`, `window`,
`screenshot`, `windows`), using the same fields as the underlying operations.
Omit generation/lease inside steps; one revocable 30-second lease covers them.
Input requires current full-desktop geometry, window actions require identity,
and screenshots require an explicit new output path. Errors report the completed
prefix and release control; there is no rollback, lease renewal, or automatic
retry. Keep waits and slow application work outside sequences.

Run `desktop doctor` for session, dependency and XRDP service diagnostics. It
does not start or restart anything and does not capture user content. A healthy
report does not qualify RDP reconnect, clipboard, or application responsiveness.

## Human handoff and logout

Before the human takes control, run `infra-tools desktop control pause`. This
revokes agent control while preserving screenshots and human RDP input. Resume
with `infra-tools desktop control resume` when the human hands control back.
Agents must honor pause; it coordinates same-account tools rather than isolating
untrusted code. Ordinary RDP input does not automatically pause agent input.

The human can open **Shared Desktop Control** from the application menu to see
control status and pause/resume agents. `desktop handoff` opens the same window
while agent control is enabled. Closing it does not resume paused agents; its
buttons remain available during pause. It is a control window, not an automatic
mouse-activity detector or permanent tray indicator.

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
