# T3 Code server

infra-tools supports T3 Code as a server-side web interface. It does not install
or manage the T3 Code desktop AppImage.

Use either the focused profile:

```bash
infra-tools setup server_dev vm.example agent \
  --t3code-ready \
  --access-source 192.168.1.0/24
```

or select the interface and providers explicitly:

```bash
infra-tools setup server_dev vm.example agent \
  --agent-tool gh \
  --agent-tool codex \
  --web-interface t3code \
  --device-pairing t3code \
  --git-access read-write \
  --access-source 192.168.1.0/24
```

The usual client is the separately installed T3 Code desktop or mobile app.
Generate a one-time URL from the control system:

```bash
infra-tools agent web pair vm.example agent
```

T3 Code sessions can expose collaborative preview tools through the client.
Prefer those tools for interactive page inspection when available. To retain a
VM-local Chromium fallback for SSH-only Codex or OpenCode sessions, request it
explicitly during setup:

```bash
infra-tools setup agent_code_vm vm.example agent \
  --browser-automation playwright
```

Agent-enabled T3 setups install managed workflow skills for T3 operation,
isolated Git worktrees, deployment smoke checks, VM triage, and the HTTPS
gateway. The workspace skill uses the safe local lifecycle command:

```bash
infra-tools agent workspace create ~/repos/PROJECT TASK --json
infra-tools agent workspace remove WORKTREE --dry-run --json
```

The removal path rejects dirty, untracked, or unmerged work and cannot remove
the primary checkout. For a shareable diagnostic snapshot that omits log and
credential contents, use `infra-tools agent support-bundle`.

## Service and update model

infra-tools uses T3 Code's supported per-user background service. Upstream owns
the launcher, immutable version directories, service state, updates, and
rollback. infra-tools adds a systemd drop-in for the configured workspace,
host, port, PATH, and GitHub CLI environment.

The service unit is:

```text
~/.config/systemd/user/t3code.service
```

Its infra-tools settings are:

```text
~/.config/systemd/user/t3code.service.d/infra-tools.conf
```

User lingering is enabled so the service starts at boot without an interactive
login. Inspect it as the target user:

```bash
systemctl --user status t3code.service
journalctl --user -u t3code.service -n 100 --no-pager
tail -n 100 ~/.t3/userdata/logs/boot-service.log
```

The upstream launcher writes application startup failures, including native
module load errors, to `~/.t3/userdata/logs/boot-service.log`. systemd's journal
primarily records the launcher lifecycle.

T3 Code does not silently update after setup. A normal infra-tools rerun keeps
the active healthy version. The T3 client can offer an explicit **Update
server** action for this background service. The following host-side commands
are also supported:

```bash
# As the target user, using T3 Code's documented updater:
env -u npm_config_dangerously_allow_all_scripts \
  -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
  -u npm_config_allow_scripts \
  -u NPM_CONFIG_ALLOW_SCRIPTS \
  CC=gcc \
  CXX=g++ \
  npm_config_strict_allow_scripts=false \
  npm_config_foreground_scripts=true \
  npx --yes --package=t3@latest -c \
  'env -u npm_config_allow_scripts \
    -u NPM_CONFIG_ALLOW_SCRIPTS \
    -u npm_config_dangerously_allow_all_scripts \
    -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
    t3 service update'
infra-tools agent doctor --capability t3code --fix

# From infra-tools:
infra-tools setup server_dev vm.example agent --refresh-packages ...
```

The direct `npx` command is expected to work after infra-tools setup because
both commands operate on the same upstream-managed user service. If the
desktop client and server differ, update the service to the client version:

```bash
env -u npm_config_dangerously_allow_all_scripts \
  -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
  -u npm_config_allow_scripts \
  -u NPM_CONFIG_ALLOW_SCRIPTS \
  CC=gcc \
  CXX=g++ \
  npm_config_strict_allow_scripts=false \
  npm_config_foreground_scripts=true \
  npx --yes --package=t3@CLIENT_VERSION -c \
  'env -u npm_config_allow_scripts \
    -u NPM_CONFIG_ALLOW_SCRIPTS \
    -u npm_config_dangerously_allow_all_scripts \
    -u NPM_CONFIG_DANGEROUSLY_ALLOW_ALL_SCRIPTS \
    t3 service update'
infra-tools agent doctor --capability t3code --fix
```

During a refresh, an upstream updater failure does not take down a previously
working installation. If the managed service file and active runtime remain
valid, infra-tools restarts and health-checks that runtime, reports that the
runtime was retained instead of updated, and continues setup. A first install,
a damaged runtime, or a failed readiness check remains fatal. Updater failures
include bounded diagnostics from both the beginning and end of npm's output so
an earlier npm error is not hidden by a later successful native-build message.

Keep the npm settings scoped to the trusted T3 updater. npm 12 blocks native
dependency scripts by default, but inherited `allow-scripts` or
`dangerously-allow-all-scripts` settings cannot be used by T3's nested
project-scoped install: npm rejects that combination with `EALLOWSCRIPTS`.
This also applies when npm reads `allow-scripts` from a user or global
`.npmrc`: the outer `npx` re-exports the setting before T3 starts. infra-tools
removes only those policy variables inside the `npx` command boundary, lets
the upstream install stage an otherwise valid runtime, then uses a short-lived
npm config that allowlists only `node-pty` and `msgpackr-extract` while
rebuilding them. Other npm settings remain available and the target user's
normal npm configuration remains unchanged.

T3 v0.0.35 also invokes `loginctl enable-linger` without a username. That can
fail in the sessionless `runuser` environment used by remote setup even after
infra-tools has enabled lingering as root. During the upstream update only,
infra-tools places a short-lived `loginctl` compatibility shim first in PATH;
it confirms lingering is already enabled, otherwise adds the validated target
username to that exact no-argument request, and delegates every other
invocation unchanged. The shim is removed immediately after the updater exits.

T3's published `node-pty` package has no Linux prebuild, so infra-tools also
selects the `gcc` and `g++` provided by `build-essential` for setup-time and
service-initiated updates. This prevents a stale inherited `CC` or `CXX` value
from selecting a missing versioned compiler. infra-tools validates the native
module, rebuilds an incomplete active runtime, and waits for several
consecutive healthy service and HTTP checks before setup succeeds. The same
repair is available after setup:

```bash
infra-tools agent doctor --capability t3code --fix
```

As of 2026-08-27, infra-tools was checked against T3 Code v0.0.35. That release
uses service-state protocol 2 and requires Node.js `^22.16`, `^23.11`, or
`>=24.10`, the same requirement as the previous release. See the upstream [background-service documentation](https://github.com/pingdotgg/t3code/blob/main/docs/user/background-service.md),
[update documentation](https://github.com/pingdotgg/t3code/blob/main/docs/user/updating.md),
and [v0.0.35 release](https://github.com/pingdotgg/t3code/releases/tag/v0.0.35).

Older infra-tools installations used a root-owned
`infra-tools-t3code.service` and a separate npm runtime. A subsequent setup
stops that service, starts and validates the upstream user service, and only
then disables and removes the old unit and clears its retained failed state.
The old service is restarted if the migration fails.

Removing desktop support from infra-tools does not delete an AppImage that an
older setup placed in a user's home. After confirming the files were not
replaced with user-managed content, that retired installation can be removed
manually:

```bash
rm -- "$HOME/.local/share/t3code/t3code.AppImage"
rm -- "$HOME/.local/bin/t3code"
rm -- "$HOME/.local/share/applications/t3code.desktop"
rmdir --ignore-fail-on-non-empty "$HOME/.local/share/t3code"
```

## Network behavior

The safe default is loopback:

```bash
--web-interface t3code
--web-interface-host 127.0.0.1
--web-interface-port 3773
```

infra-tools publishes a managed HTTPS endpoint through its shared gateway. The
plain HTTP listener remains for local compatibility. For a non-loopback bind,
declare private source networks:

```bash
--web-interface-host 0.0.0.0
--web-interface-source 192.168.1.0/24
```

A non-loopback bind is rejected unless UFW is active and a private or
non-global allowlist is present. infra-tools reconciles only its own labeled
UFW rules and refuses conflicting unmanaged rules on the managed ports.

The protected device-pairing broker uses port 3774 by default. Its Basic Auth
credential is staged for setup and is not written to the saved setup command.
Prefer the HTTPS endpoints printed during setup.

## Git and provider behavior

T3 Code runs as the target user. Git identity, GitHub CLI credentials, provider
credentials, repositories, and the workspace therefore stay in that user's
home and configured workspace.

Useful checks:

```bash
infra-tools agent doctor --capability t3code --capability host
gh auth status
git config --global --get user.name
git config --global --get user.email
infra-tools agent support-bundle
```

The doctor validates the upstream service-state protocol and selected immutable
runtime, required native terminal module, user service, endpoint, pairing
helper, Git identity, and managed agent skill. Add `--fix` to rebuild an
incomplete native runtime, repair GitHub's credential helper, or restart an
inactive user service. The separate host capability reports memory, swap,
filesystem and agent-storage headroom, T3 cgroup usage, recurring maintenance
state, and pending reboots. Capacity warnings do not make an otherwise healthy
service fail; critical disk pressure and recorded maintenance failures do.

## Related documentation

- [Device pairing](DEVICE_PAIRING.md)
- [Command-line reference](COMMAND_LINE.md)
- [Workstation and agent profiles](WORKSTATIONS.md)
