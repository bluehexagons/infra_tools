# Godot Engine

Use `--godot` with any setup profile to install the newest stable standard
Godot Engine release. Godot 4.7.2 was the current stable release when this
support was added. The installer resolves the current version at run time, so
the repository does not need a version bump for later stable releases.

```bash
# Graphical editor on an agent workstation
infra-tools setup agent_workstation 192.168.1.40 agent --godot

# Headless editor/runtime on an SSH-only agent VM
infra-tools setup agent_vm 192.168.1.41 agent --godot
ssh agent@192.168.1.41 'godot --headless --version'

# Web export and itch.io/Steam publishing tools
infra-tools setup agent_workstation 192.168.1.42 agent \
  --godot-bundle web \
  --godot-bundle publishing
```

The standard Linux editor binary supports both windowed use and the
`--headless` display/audio drivers. The setup also installs a desktop entry, so
a graphical session can launch the editor without a separate build. .NET/C#
builds and export templates are not installed by `--godot` alone.

## Workflow bundles

`--godot-bundle BUNDLE` is repeatable, automatically enables `--godot`, and
currently accepts these bundles:

| Bundle | Installed tooling |
| --- | --- |
| `web` | Version-matched web export templates for regular, single-threaded, and GDExtension-enabled debug/release exports |
| `publishing` | Butler for itch.io and, on x86_64, the SteamCMD command-line publisher |

The web bundle selects the official export-template TPZ matching the active
engine release and uses the same bounded HTTP range approach as Godot 4.7's
Export Template Manager. It reads the ZIP directory, downloads only
`version.txt` and the web template members, and verifies each member through
the ZIP CRC while extracting it. This avoids staging or transferring the full
all-platform archive. The cache is kept under `/opt/godot/export_templates`;
files are copied into the configured account's
`~/.local/share/godot/export_templates/VERSION` directory so graphical users
and agents running as that account see the same export targets.

The publishing bundle installs verified Butler GitHub releases system-wide as
`butler`. It also installs Valve's pinned SteamCMD bootstrap in the configured
account's `~/.local/share/infra_tools/steamcmd` directory and exposes it as
`~/.local/bin/steamcmd`. SteamCMD performs its supported self-update when setup
or weekly maintenance runs. Valve does not provide a Linux ARM64 SteamCMD
client, so ARM64 targets receive Butler and report that SteamCMD was skipped.
Because SteamCMD updates its own user-owned installation, the publishing
bundle requires a non-root setup account.

infra-tools does not collect, stage, or persist publishing credentials. Sign in
as the configured account only when needed:

```bash
butler login
steamcmd +login YOUR_STEAM_ACCOUNT
```

Combine `web` with an explicit browser or the existing Playwright integration
when exported games need browser smoke tests; the bundle itself does not alter
browser or agent configuration.

## Release and integrity policy

Godot itself is not installed from Debian's default APT sources. infra-tools
queries stable releases from the official `godotengine/godot` repository,
selects the matching x86_64 or arm64 Linux archive, requires the
publisher-provided SHA-256 from GitHub release metadata, and verifies the
archive before extracting its single expected binary. `curl` and CA
certificates are ordinary APT prerequisites; the engine version does not
depend on Debian's package catalog.

Verified releases are stored under `/opt/godot/releases`. The active release is
selected through `/opt/godot/current`, with system-wide `godot` and `godot4`
launchers in `/usr/local/bin`. Those launchers are on the normal system path for
the configured user and coding agents, whether they run from SSH, a desktop,
T3 Code, or another agent interface. Setup verifies the selected binary with a
headless version command before activation.

## Automatic updates

`--godot` installs `auto-update-godot.timer`. It checks the official stable
release channel each Sunday at 06:30, with the standard randomized delay, and
activates a newer verified release. The same run installs matching web
templates for every registered bundle user, updates Butler from its verified
stable release channel, and invokes SteamCMD's self-update for publishing
users. This check deliberately uses newest stable releases rather than the
general dependency freshness delay.

```bash
sudo systemctl status auto-update-godot.timer
sudo systemctl start auto-update-godot.service
sudo journalctl -u auto-update-godot.service -n 100 --no-pager
```

Engine activation failures leave the previously activated version in place.
If an older setup refresh already removed Godot's state metadata, the next run
downloads and verifies the matching official engine archive again before
repairing that state; it does not trust the release-directory name alone.
Bundle failures preserve already installed bundle files, fail the maintenance
job, and can use the normal `--notify` targets; if the engine already advanced,
the next successful run installs its matching web templates. Rerunning the
saved setup reconciles the same installation and timer configuration.

The roadmap reserves later bundle implementations for `dotnet`, `android`,
`gdextension`, and `assets`; these names are not accepted by the CLI until
their installation and update contracts are implemented.
