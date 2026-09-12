# One shared desktop session per machine

Status: proposed project plan, 2026-09-12. Implementation has not started.

## Objective and scope

Make every infra-tools-managed desktop use one graphical session owned by
one configured non-root account. A human or an agent can start it, attach to
it, and use its applications. Disconnecting leaves it running; desktop logout
ends it. This replaces the current model across desktop setup, rather than
adding an agent-only desktop alongside existing sessions.

The primary acceptance target is a Debian agent VM with standard emulated
graphics and software rendering. Apply the same lifecycle to
`workstation_desktop`, `pc_dev`, `workstation_dev`, `agent_workstation`, and
`agent_code_vm`, and to desktop capability explicitly enabled on other
profiles. Keep `agent_vm` headless by default. Bare-metal desktop setup and
existing local desktops need an explicit migration path under the same
single-session contract.

One session means one desktop across the machine, not one session per remote
client or one per username. Other Unix accounts, SSH sessions, services, and
concurrent coding agents remain possible. Infra-tools does not support
creating additional managed graphical sessions. It does not attempt to
prevent an administrator from manually launching an unrelated X server.

## Current implementation and resulting changes

| Current behavior | Required change |
| --- | --- |
| `desktop/xrdp_steps.py` lets XRDP sesman create Xorg/xorgxrdp desktops; `MaxSessions` defaults to ten. | A single lifecycle owner creates the desktop; remote access attaches to it. Setting `MaxSessions=1` alone is insufficient. |
| `desktop/config/xrdp_xsession.template` starts the desktop and D-Bus from RDP login. | Move transport-independent startup and teardown into the shared session implementation. |
| `plugins/desktop.py` composes desktop installation and optional RDP; workstation profiles call it. | Make the shared session the base desktop capability, with remote transports as optional attachments. |
| `plugins/server.py` does not currently call the desktop capability builder. | Wire explicitly requested desktop capability through the server composition without installing it on all agent VMs. |
| Local workstation documentation preserves GNOME on the console and starts XFCE separately through RDP. | Retire the two-desktop model; migrate to one selected desktop or report that the existing installation cannot yet be adopted. |
| Desktop choices are XFCE, i3, Cinnamon, and LXQt; package installation can also install a display manager. | Validate each supported environment and ensure its display manager cannot independently create another user desktop. |
| Configuration, CLI, serialization, display output, and tests expose session counts and disconnect cleanup. | Replace these settings with the fixed lifecycle and migrate stored configurations. |
| Existing agent browser tools operate their own browser automation context. | Add explicit shared-desktop tools; do not assume browser tooling already controls native applications. |

See [XRDP](../XRDP.md), [workstations](../WORKSTATIONS.md), and the
[desktop maintenance audit](DESKTOP_AGENT_MAINTENANCE_AUDIT_2026-08-09.md)
for the current operator contract and prior reliability work. This plan owns
the new architecture; relevant outstanding desktop audit validation feeds
its acceptance suite.

## Fixed lifecycle contract

| Request or event | Required behavior |
| --- | --- |
| Authenticated start/connect with no session | Start the configured desktop account's session, wait for readiness, then attach. |
| Start/connect while starting | Join the in-progress operation; never spawn another desktop. |
| Start/connect while running | Return or attach to the existing session without restarting applications. |
| Viewer disconnect, network loss, or agent process exit | Leave the desktop running indefinitely. |
| Desktop logout | End the desktop, its display, and session-owned applications; invalidate its runtime metadata. |
| Logout canceled by an application | Keep the existing session and report that logout did not complete. |
| Start/connect during logout | Return a stopping/retry result; do not queue an implicit replacement session. |
| Desktop/display crash | Clean up the failed session, record the failure, and wait for a new explicit start. |
| Remote gateway crash/restart | Preserve the desktop; allow later attachment to the same session. |
| VM reboot or shutdown | End the session; do not claim to preserve live processes across reboot. |
| Boot after shutdown | Make the start/connect endpoint available; leave the desktop stopped until requested. |

The lifecycle controller may be supervised and restarted. The desktop must
not have an unconditional restart policy. Remote viewers must not silently
create a replacement desktop through automatic reconnection after logout:
attachment carries a session generation, and starting a new generation
requires a fresh user/agent start request.

Use states `stopped`, `starting`, `running`, `stopping`, and `failed`, with a
machine-wide startup lock and a unique generation for each session. Treat
process and display readiness as evidence; a leftover PID or environment file
does not establish that a session is alive. Bound startup and teardown waits
and return actionable errors.

Desktop logout must not terminate independent SSH, tmux, T3 Code, or coding
agent services. Use session-specific process supervision rather than killing
every process belonging to the account. Verify applications launched through
D-Bus or user services are accounted for during teardown.

## Architecture and backend decision

The architectural decision is fixed: one desktop lifecycle owner, one
configured owner account, and transports that attach to that desktop. The
display backend is selected by an initial compatibility prototype, not by
assuming the existing backend can be changed without regressions.

Evaluate these two candidates, then select one default implementation:

| Candidate | Why evaluate it | Required evidence |
| --- | --- | --- |
| Supervised XFCE/X11 on TigerVNC's virtual X server | Natural independent startup on VMs; remote clients share the same virtual display. | Resize, application compatibility, logout, remote-first startup, and RDP attachment if retained. |
| Supervised console Xorg with an existing-display sharing server | Can make local console and remote access show the same desktop; relevant to bare-metal workstations. | Rootless/seat permissions, operation without a human console login, emulated graphics, and sharing/resize behavior. |

[TigerVNC documents](https://tigervnc.org/doc/Xvnc.html) a virtual X display,
shared connections, desktop-size requests, and disconnect-related lifetime
settings. These make it a candidate, not proof of compatibility with this
repository's supported applications or clients.
[x0vncserver](https://tigervnc.org/doc/x0vncserver.html) instead shares an
existing X display and does not create the desktop.

The current XRDP implementation explicitly excludes Xvnc because of recorded
resize/freezing problems. Reproduce that scenario against the exact candidate
package versions. Do not delete the existing workaround based only on
upstream feature descriptions. Prefer the virtual backend for VM simplicity
only if it passes the compatibility gate. If physical-console requirements
require a distinct display adapter, both adapters must use the same lifecycle
and only one may be selected on a machine; do not retain parallel independent
desktop stacks.

Start qualification with XFCE/X11. Test i3, LXQt, and Cinnamon before claiming
continued support. Existing GNOME/Wayland installations need either a tested
adoption adapter or a documented conversion to a qualified environment; a
second XFCE desktop is no longer the fallback. Do not silently replace an
existing user's desktop during routine setup.

For VMs, the hypervisor console may remain a text/recovery console, as it is
not a second user desktop. If graphical console access is offered, it must
show or attach to the shared session. For physical workstations, local human
login/start must reach that same session, and remote-first startup must not
prevent later local attachment. Include this in backend selection rather
than leaving it as a post-release exception.

## Session implementation and human access

Implement the lifecycle in `desktop/`, exposed through the existing CLI and
plugin boundaries. Use systemd supervision appropriate to the machine and
account. Define how PAM/logind, the user runtime directory, D-Bus, and X
authentication are established without an interactive SSH or console login.
Validate required capabilities; unsupported hosts receive a clear setup
error before mutation. Never use `can_modify_kernel()` as a service/package
capability shortcut.

Keep display identity, generation, readiness, and authentication references
in private runtime state. Launch applications with the current session's
`DISPLAY`, `XAUTHORITY`, D-Bus address, and runtime directory. Do not export
stale display variables globally into shell profiles or unrelated services.
Resolve the actual account home/UID, validate paths and identities, and use
argument arrays rather than shell interpolation for application launch.

Human connection must work from a stopped desktop. Authentication precedes
session creation; an unauthenticated TCP connection must not start a desktop.
The connection entry point calls the same start-or-attach operation as agents.
Prototype this end to end; a VNC listener that exists only after an agent
starts the desktop does not satisfy the requirement.

Preserve RDP access if a qualified adapter can attach to the managed desktop
without delegating desktop creation back to sesman. Explicitly test the
authentication-to-start bridge and existing client behavior. If this cannot
meet the contract, document RDP retirement and a replacement human connection
workflow before migration. Do not silently reinterpret `--rdp` as VNC.

Native VNC and an optional browser viewer are alternative access surfaces,
not requirements to ship three transports. Deliver one fully supported human
entry point first. Keep display/backend sockets private, preserve current
access-source restrictions, and carry forward TLS and certificate health
checks for whichever network-facing service remains. Loopback alone is not
authentication against other local accounts. Reuse existing gateway and
authentication infrastructure where suitable rather than adding a public,
unauthenticated remote-desktop port.

Define a single desktop geometry and resize owner. Other viewers scale the
same framebuffer; competing clients must not continually resize it. Preserve
clipboard policy where supported. Inventory audio, drive redirection,
multi-monitor behavior, keyboard layouts, and lock/unlock support; explicitly
document any removed capabilities rather than carrying unsupported flags.
Locking preserves the session; reconnecting must not bypass the lock.

## Agent interface and shared control

Proposed command shapes, subject to the existing CLI conventions:

```text
infra-tools desktop status --json
infra-tools desktop start --json
infra-tools desktop exec -- APPLICATION ARGUMENTS...
infra-tools desktop screenshot --output PATH
infra-tools desktop control pause
infra-tools desktop control resume
infra-tools desktop logout
```

These are planned commands, not currently available commands. Keep
`infra-tools desktop ...` runtime operations distinct from the existing
`infra-tools local desktop ENVIRONMENT` installation command. Default `exec`
and screenshot to requiring a running session; `start` is the explicit
creation operation. Provide an authenticated human connect action that
performs start-or-attach.

Expose equivalent bounded screenshot, pointer, keyboard, scroll, window, and
launch operations through a managed desktop tool adapter for agents. Return
the session generation and geometry with screenshots so input based on an old
session or resolution can be rejected. Scope control to the configured
account and active session. Register the tool only when desktop capability is
installed, and add a managed workflow skill using the existing skill delivery
pattern. Browser automation retains its separate lifecycle unless explicitly
launched into this desktop.

Provide human takeover by pausing agent desktop mutations while keeping
observation available. Serialize agent input sequences using a control lease
so multiple agents do not interleave typing and clicks. Human takeover revokes
the lease; resume is explicit. This is cooperative coordination within a
shared account, not an isolation boundary against arbitrary shell commands.
Do not promise automatic inference of human intent from mouse movement.

### Managed skills and choosing the right tool

Ship desktop guidance as part of the capability, not as optional follow-up
documentation. The managed desktop skill must describe the configured desktop
environment, available application/tool discovery, software-rendering limits,
the shared account/session, start and status operations, human connection and
takeover, and disconnect versus logout. Discover live state rather than
assuming a running desktop, a fixed display number, or installed applications.

Use this task-routing policy in the desktop skill and the existing browser
skills:

| Task | Preferred system |
| --- | --- |
| Routine browser testing, DOM assertions, console/network inspection, repeatable interactions, or VM-loopback access | Healthy managed VM-local Playwright. |
| Browser work the human should watch or participate in, or verification of the connected client's routes/trust | Available T3 Code collaborative browser. |
| Native GUI application work, desktop/window behavior, OS dialogs, or an explicit request to operate the human's shared desktop | Shared desktop tools. |
| File edits, builds, service checks, or tasks with a suitable CLI/API | Existing shell, API, or domain-specific tools. |

Browser testing should almost always use the available browser systems. Keep
the existing choice between T3 collaboration and Playwright based on the task;
do not introduce a mandatory T3-first probe when Playwright is the appropriate
tool. A running desktop or an installed graphical browser is not a reason to
switch routine web testing to desktop screenshots and clicks.

Use the desktop browser only when the task explicitly concerns that browser
session or desktop integration, the user requests it, or the preferred browser
systems are unavailable or cannot exercise the required behavior. Before a
fallback, perform the installed browser skill's bounded availability/health
checks and state the concrete reason for switching. If T3 is unavailable but
healthy Playwright fits the task, use Playwright. A failed application test is
not evidence that the browser tooling is unavailable. If no suitable browser
surface exists, report the coverage limit rather than treating a desktop
fallback as equivalent evidence.

Keep the browser contexts distinct: T3 preview runs in the connected client's
context; managed Playwright and the shared desktop browser run on the VM but
may have different profiles, cookies, and authentication. Do not transfer
profiles or credentials automatically. Report which surface produced test
evidence, especially when the network origin or user session matters.

Add the desktop skill under `common/agent_skills/` and reconcile its delivery
with desktop capability installation/removal. Update routing and cross-links
in `infra-tools-browser-testing`, `infra-tools-t3-preview-testing`, and
`infra-tools-playwright-testing`, plus the agent skill catalog and relevant
native-application guidance. Preserve each VM's capability-specific browser
skill selection; do not advertise unavailable desktop or browser tools.

## Configuration and migration

Define a versioned desktop configuration with one owner, selected environment,
remote access policy, and any qualified geometry/control options. There is no
session-count setting and no disconnect-triggered session destruction.

Update parsing, validation, saved-configuration loading, command generation,
remote forwarding, display summaries, completion, and tests together. Remove
`rdp_max_sessions`, `rdp_kill_disconnected`, and
`rdp_disconnected_timeout` from the active model. Decide whether the existing
idle timeout remains a viewer-disconnect option; it must never destroy the
desktop. Old command-line options should produce migration guidance rather
than be accepted and ignored.

Provide a narrow versioned loader migration for saved configurations:
translate old default session policy into the new fixed policy; surface
explicit nondefault multi-session/cleanup values as behavior changes in the
migration report. Do not preserve a legacy multi-session execution path.
Audit existing group-based RDP access: only the configured desktop owner may
start/own the desktop, with any human gateway identities explicitly authorized
to share that account's session.

Migration sequence:

1. Inspect installed packages, managed files, display managers, active
   sessions, saved configuration, remote access, and account ownership.
2. Produce a dry-run report showing the selected owner/environment, settings
   removed, service changes, access changes, and rollback material.
3. Stage and validate the new configuration without restarting the running
   desktop. Never auto-select and kill surplus sessions to satisfy the limit.
4. Require old graphical sessions to be logged out before cutover. If any
   remain, report the pending cutover and leave current access working.
5. Activate the new lifecycle and attachment service, disable old managed
   session-creation routes, and verify start/connect/logout behavior.
6. Remove obsolete managed units, templates, configuration, firewall rules,
   monitors, and packages only after establishing ownership and remaining
   dependencies. Preserve unrelated desktop files and application data.

Back up managed configuration and package state before cutover. Rollback
restores the previous configuration/access stack, not unsaved GUI processes.
Do not force logout for an automatic rollback after users have begun working
in the new session. Keep deployment markers sufficient to resume a failed
cutover. Ordinary reruns and maintenance must not restart an active desktop;
defer disruptive display/package changes to a session-free maintenance window.

## Delivery sequence

| Phase | Deliverable | Exit gate |
| --- | --- | --- |
| 1. Compatibility prototype | Disposable standard-graphics VM; compare candidate backends, human-first startup, RDP feasibility, resize, and local-console requirements. | Record versions and live evidence; choose the default backend and supported transport/environment matrix. |
| 2. Shared runtime | Lifecycle owner, private runtime state, startup locking, readiness, launch, logout, crash cleanup, and JSON status. | Race/lifecycle tests pass; no automatic recreation after logout; independent agents survive. |
| 3. Human attachment | Authenticated start/connect and reconnect, lock behavior, geometry policy, and access restrictions. | Human and agent see the same application process across disconnects; transport restart preserves it. |
| 4. Agent control | Screenshot/input adapter, application launch, generation checks, takeover, managed tool/skill registration, and browser/desktop task routing. | Native application task completed while a human observes and takes over; routine browser tasks select T3 or Playwright when suitable and available. |
| 5. Setup and migration | All desktop profile builders, server opt-in, saved-config migration, old-stack cleanup, and rollback. | Fresh install, existing host migration, idempotent rerun, and interrupted cutover pass. |
| 6. Qualification and documentation | Supported environment/client matrix, maintenance checks, troubleshooting, and release notes. | Acceptance matrix below passes before changing desktop defaults. |

Land cohesive implementation changes in this order. Do not ship a temporary
agent desktop beside the legacy desktop as the final migration strategy.

## Validation and completion criteria

Unit and integration tests mock system calls and use temporary directories.
Prioritize state transitions, concurrent creation, canceled logout, stale
generation rejection, ownership checks, migration, and rollback over tests
that merely duplicate generated text. Run affected desktop, configuration,
validation, plugin, firewall, and agent-tool suites, then the relevant wider
suite. Use setup dry runs; ordinary tests must not alter the development host.

Retain a reproducible live smoke procedure on disposable machines:

| Scenario | Passing evidence |
| --- | --- |
| Agent starts first; human connects later | Same generation, display, application PID, and visible document. |
| Human connects first from stopped state | Authentication starts exactly one desktop; agent can discover and operate it. |
| Simultaneous starts/repeated connects | One graphical session and no duplicate desktop process tree. |
| Disconnect all viewers and end initiating agent | Applications remain alive and reconnect returns to them. |
| Logout with viewer auto-reconnect enabled | Desktop ends and remains stopped until a fresh explicit start. |
| Unsaved-document logout prompt | Cancel leaves the same session usable; force termination is a separate explicit action. |
| Display crash, stale runtime state, or startup failure | Bounded cleanup, useful diagnostics, and successful later explicit start. |
| Gateway restart or network interruption | Desktop process identity remains unchanged. |
| Human takeover and multiple agents | Paused/stale input is rejected; input sequences do not interleave. |
| Browser testing with desktop and browser tools available | Agent chooses Playwright or T3 according to the task without starting/controlling the desktop merely to test a web page. |
| T3 unavailable, Playwright healthy | A suitable VM-origin browser task continues through Playwright; desktop is not the automatic fallback. |
| Native GUI task or justified desktop-browser exception | Desktop skill discovers the environment, explains the tool choice, and follows shared-session/takeover behavior. |
| Capability-specific skill installation/removal | Installed skills describe available tools and consistent routing; browser-only VMs are not instructed to use an absent desktop. |
| Resize, keyboard layout, clipboard, lock/unlock | Works for each claimed client; reproduce the previous XRDP resize failure case. |
| Standard emulated graphics | Browser, editor, terminal, file manager, and an applicable native GUI workflow operate without passthrough. Record responsiveness and resource usage. |
| Local and remote workstation access | Both reach the same desktop; no independent GNOME/XFCE sessions are created. |
| Migration with active legacy sessions | No application is killed; cutover reports why it is pending. |
| Headless profile and unrelated services | No implicit desktop install; logout leaves SSH, tmux, and agent services intact. |
| Reboot, maintenance, rollback, and setup rerun | Documented lifecycle holds; no unintended desktop restart or access expansion. |

Qualify supported Debian VM images and remote clients first, then the
bare-metal path and each retained desktop choice. Claim container support
only after equivalent capability and live-session checks. Do not substitute
mock-only success for the live resize/reconnect qualification.

Update `WORKSTATIONS.md`, `XRDP.md` (or its replacement transport guide),
`COMMAND_LINE.md`, `LOCAL_MAINTENANCE.md`, `MACHINE_TYPES.md`, `PROXMOX.md`,
agent guides/skills, authentication guidance, and maintenance documentation.
Describe the shared desktop as its own capability; do not revive the retired
T3 Code desktop AppImage integration.

The project is complete when every supported desktop setup uses the single
session lifecycle, either participant can initiate it, both operate the same
applications, disconnect preserves it, logout ends it without recreation,
and legacy session creation/configuration paths have been removed after a
tested migration. Multi-user desktops, persistent GUI processes across
reboots, and GPU passthrough are outside this project.
