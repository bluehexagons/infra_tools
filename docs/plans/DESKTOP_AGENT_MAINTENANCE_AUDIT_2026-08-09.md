# RDP Desktop Agent Host and Maintenance Audit (2026-08-09)

Status: active follow-up plan. Password persistence, managed X.Org deployment,
unsupported session cleanup, RDP source/bind policy, channel defaults, and the
Proxmox emulated-display profile have been addressed. Native session lifecycle
controls are now saved and validated. Certificate lifecycle, workload-aware
maintenance, configuration compatibility, physical-GPU acceleration, and live
desktop verification remain larger work.

## Scope and recommended baseline

This review traced the RDP-capable coding-desktop path from argument
normalization and workstation step selection through user creation, XRDP,
XFCE, agent tools, firewall and fail2ban policy, saved state, and recurring
systemd maintenance.

The recommended baseline is:

```bash
infra_tools setup workstation_dev 10.0.0.25 agent \
  --desktop xfce --rdp --password "$RDP_PASSWORD" \
  --rdp-source 10.0.0.0/24 \
  --agent-suite terminal --copy-config \
  --repo https://github.com/user/project.git
```

`workstation_dev` adds XFCE, a browser, Visual Studio Code, and the shared CLI
bundle. The `terminal` agent suite adds GitHub CLI, Codex CLI, Claude Code,
OpenCode, and common coding utilities. Use `--agent-suite desktop` only when
the optional T3 Code AppImage is also wanted, or `full` when Node.js, Python
tooling, and Go should be implicit.

RDP is opt-in because it needs a Unix account password and opens an additional
network service. The setup password is transmitted in a mode-`0600` argument
file that the remote entry point removes immediately after reading. It is no
longer retained in saved setup state.

## Maintenance currently applied

On a Debian VM or bare-metal target, the baseline inherits:

| Unit | Behavior | Desktop-agent effect |
| --- | --- | --- |
| `security-monitor.timer` | Reads fail2ban, auditd, and SSH events every 15 minutes | XRDP bans are visible through fail2ban events, but there is no RDP-specific session or certificate health check |
| `auto-update-apt.timer` | Runs a daily non-removing distribution upgrade | Updates XRDP, X.Org, the browser/VS Code when APT-managed, GitHub CLI, and Debian coding tools |
| `cleanup-maintenance.timer` | Cleans bounded root caches, journals, and strictly named stale temp artifacts weekly | Does not comprehensively manage the desktop user's browser, editor, Flatpak, or agent caches |
| `auto-restart-if-needed.timer` | Checks daily and after boot for `/var/run/reboot-required` | Defers for login sessions until the force deadline, then can restart despite an active RDP or agent workload |

`--agent-suite full`, `--node`, or `--python` also add the user-scoped Node.js
and uv update timers. Codex CLI, Claude Code, and OpenCode updates remain an
explicit `infra_tools agent update` action; T3 Code has no managed update path.
See the [CLI-only agent audit](AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md) for
the shared agent-tool lifecycle work.

## Findings addressed in this audit

### RDA-01: The RDP login password was persisted in saved setup state

`SetupConfig.to_dict()` removed share credentials but retained `password`, so
remote setup wrote the Unix/RDP password to `/opt/infra_tools/state/setup.json`.
The file was root-only, but persistence contradicted the documented contract
and unnecessarily extended the lifetime of a login credential.

Serialization and the state writer now both exclude the field. Loading a
legacy state file removes the field and atomically rewrites the sanitized file.
The short-lived remote argument file remains mode `0600` and is unlinked as
soon as it is parsed.

### RDA-02: The managed xorgxrdp configuration was normally skipped

The setup wrote `/etc/X11/xrdp/xorg.conf` only when it did not exist, but the
Debian `xorgxrdp` package supplies that path during installation. Normal fresh
installs therefore skipped the documented software-rendering, cursor, DPMS,
and 4K virtual-screen settings.

Setup now backs up the first observed file to `xorg.conf.bak` and deploys the
managed configuration on every run. A generated-content test and an
existing-file regression test cover the behavior.

### RDA-03: The configured session-cleanup hook was unsupported dead code

The generated `sesman.ini` used `EndSessionCommand`, but that key is not part
of XRDP's current `sesman.ini` contract. The associated script therefore did
not provide the cleanup guarantee described by its name. If invoked manually,
its username-wide `pkill` operations could also affect unrelated sessions.

The unsupported directive, script, and tests were removed. XRDP's native
`Policy`, `KillDisconnected`, `DisconnectedTimeLimit`, and `IdleTimeLimit`
settings are the supported basis for future session lifecycle policy. Upstream
documents these controls in its
[sesman configuration](https://github.com/neutrinolabs/xrdp/blob/devel/sesman/sesman.ini.in).

### RDA-04: RDP exposure and data-transfer policy were implicit

XRDP listened on every IPv4 interface, UFW admitted globally rate-limited port
3389 traffic, and the generated configuration did not contain an enforceable
channel allowlist. Operators could not save or replay a narrower policy.

Setup now accepts a validated `--rdp-bind-address` and repeatable validated
`--rdp-source` IP/CIDR values. UFW installs replacement source rules before
removing broad access, comment-tags managed rules, and removes stale managed
entries without touching operator rules. An omitted source deliberately keeps
the historical global rule rather than silently breaking existing access.

The coding-host channel baseline keeps dynamic virtual channels and clipboard,
while drive/device, printer, audio, RemoteApp, and video redirection are denied.
Clipboard, drive/device, and audio policy are explicit saved CLI settings.

### RDA-05: Session lifecycle could not be bounded safely

The managed session configuration fixed `MaxSessions=10` and otherwise relied
on implicit XRDP defaults. Operators could neither reduce concurrency nor
configure supported idle/disconnected behavior without editing a file that the
next setup run replaced.

Saved, validated settings now render `MaxSessions`, `KillDisconnected`,
`DisconnectedTimeLimit`, and `IdleTimeLimit`. Defaults preserve reconnectable
sessions. Destructive disconnected-session cleanup requires an explicit boolean
and positive retention interval, and the setup preview shows the effective
limits. This bounds abandoned sessions without a username-wide process killer.

### RDA-06: Proxmox desktop VMs had no graphical recovery console

Hosted VMs were created with `serial0` as both their serial device and display,
including desktop/RDP profiles. Proxmox therefore disabled VGA output and its
noVNC console showed only the serial terminal. At the same time, guest setup
treated the `vm` machine label as proof of GPU/DRI access and granted the
desktop user `video` and `render`, although the managed xorgxrdp configuration
uses `xrdpdev`, `AutoAddGPU=off`, and `UseGlamor=false`.

Desktop or RDP hosted VMs now receive VirtIO-GPU for the Proxmox recovery
console while retaining the serial socket; server-only VMs remain serial-only.
The XRDP session remains software-rendered and no longer receives unrelated
DRM group privileges. The existing VirtIO SCSI single root disk now enables
its supported per-disk I/O thread. Unit tests cover profile selection, emitted
`qm` options, and the absence of GPU-group grants.

## Larger follow-up work

### P1: RDP TLS identity, health, and safe network apply

**Risk:** explicit listener, source, and channel controls now exist, but the
backward-compatible no-source default remains globally reachable. TLS relies on
the distro's default certificate paths and setup does not verify certificate
identity, expiry, client trust, or rotation. Firewall changes are ordered to
preserve access on rule-install failure, but do not yet have a preview,
connectivity probe, or timed rollback.

Complete this area with:

1. an explicit VPN/private-network-only preset and migration guidance away
   from the compatibility global rule;
2. operator-provided or automatically enrolled certificate/key paths, file
   permissions, expiry monitoring, and rotation;
3. post-apply probes that confirm TLS-only negotiation and the effective UFW
   and fail2ban rules without exposing credentials.

Do not silently narrow an existing host's access during a rerun. This work
needs a preview, connectivity check, and timed rollback aligned with the
roadmap's safe-network-apply contract.

### P1: Workload-aware restart and session warning policy

**Risk:** session limits and native lifecycle controls are now explicit, but a
configured cleanup deadline cannot distinguish abandoned desktops from useful
agents running inside them. Independently, the host restart policy can override
all active-session deferrals after seven days.

Extend the saved maintenance/session policy with:

- warnings and a drain/hold marker visible both inside RDP and over SSH;
- detection of active agent, editor, terminal multiplexer, build, and repository
  mutation workloads without reading source or prompts; and
- post-reboot verification of XRDP login, desktop startup, tool paths,
  repositories, and timer results.

This should extend the agent-aware restart work in the CLI-only audit and use
XRDP's native lifecycle controls rather than reintroduce a process-killing hook.

### P1: Version-aware XRDP configuration and rollback

**Risk:** infra_tools replaces complete `xrdp.ini`, `sesman.ini`, and X.Org
files. APT can update XRDP independently, and upstream occasionally adds or
changes configuration fields. Static full-file replacement can therefore hide
new defaults or become incompatible, while setup does not parse-check all
rendered files or restore them when service activation fails.

Introduce a versioned renderer with:

- an explicit supported XRDP/xorgxrdp version range;
- schema-aware rendering or narrowly managed fragments where upstream permits;
- atomic file replacement, secure modes, and exact pre-change backups;
- package-provided configuration diff reporting after upgrades;
- daemon/config validation before activation; and
- rollback when reload, login smoke testing, or health verification fails.

This belongs on the shared transactional execution path, not in a second XRDP-
specific transaction framework.

### P1: Desktop-agent audit command and live smoke coverage

**Risk:** unit tests mock package installation, service state, filesystem
writes, and clients. A green test run does not prove that the target can accept
a TLS RDP login, start the requested desktop, resize through RANDR, reconnect
without data loss, or survive an XRDP/APT upgrade.

Extend the planned read-only audit surface with text and JSON results for:

- XRDP/xorgxrdp versions and supported-range status;
- service enabled/active state and recent failures;
- listener, firewall, fail2ban jail, certificate identity/expiry, and file
  permissions;
- effective session policy and abandoned-session/resource counts;
- desktop command availability and recent X.Org/session errors; and
- all expected maintenance timers, their last result, next run, and pending
  reboot age.

Add a disposable Debian VM test that performs a real non-root TLS login,
desktop launch, dynamic resize, disconnect/reconnect, and package-update
cycle. The test credential must be generated for the fixture and destroyed
with it.

### P2: GUI application provenance and lifecycle

**Risk:** APT and Flatpak applications follow their repositories, but some GUI
paths download the latest Discord or browser package directly and install it
without an independently verified digest or saved desired version. Browser
extensions are downloaded without a managed installation or update contract.

Inventory each desktop application by source and version. Prefer signed APT or
Flatpak repositories; otherwise pin an upstream version, verify a publisher
digest/signature, retain non-secret install evidence, and add explicit update
and rollback behavior. Fold GUI version health into the same audit surface as
agent tools instead of adding another updater timer per application.

### P2: Physical-GPU passthrough and xorgxrdp acceleration profile

**Risk:** VirtIO-GPU improves only the Proxmox console. Enabling xorgxrdp
glamor against a passed-through physical GPU changes the host isolation,
firmware, guest driver, device-permission, and session stability boundary. The
current software renderer must not silently switch based on the broad `vm`
machine label or the presence of an emulated DRM node.

If hardware acceleration becomes necessary, design an explicit opt-in profile
that validates IOMMU isolation and Proxmox Q35/OVMF/hostpci settings, restricts
DRM group access to the intended user, verifies the xorgxrdp build and driver
allowlist, benchmarks software versus glamor, and rolls back on login, resize,
or reconnect failure. Cover both noVNC recovery and RDP because they use
separate display paths.

## Validation requirements

- Unit tests prove passwords never enter serialized or saved setup state and
  that a legacy state file is sanitized on read.
- XRDP rendering tests cover package-preexisting X.Org configuration and reject
  unsupported directives.
- Network-policy tests cover source validation, rule reconciliation, preview,
  and rollback without risking the active management path.
- Restart tests include connected and disconnected RDP sessions, `tmux`, active
  agents, builds, explicit holds, and force-deadline behavior.
- Live VM tests cover TLS login, all supported desktop commands, resize,
  reconnect, certificate rotation, XRDP package upgrades, and failed-config
  rollback.
- Audit output must never contain passwords, tokens, clipboard contents,
  prompts, or repository file contents.

## Primary implementation evidence

- `lib/config.py`, `lib/machine_state.py`, and `remote_setup.py`
- `plugins/workstation.py`, `plugins/desktop.py`, and `plugins/security.py`
- `desktop/xrdp_steps.py`, `desktop/desktop_environment_steps.py`, and
  `desktop/config/`
- `security/security_steps.py`
- `lib/maintenance_systemd.py`
- `common/service_tools/auto_restart_if_needed.py`
- `common/service_tools/cleanup_maintenance.py`
- `tests/test_xrdp.py`, `tests/test_config.py`, and `tests/test_machine_state.py`
