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
```

The standard Linux editor binary supports both windowed use and the
`--headless` display/audio drivers. The setup also installs a desktop entry, so
a graphical session can launch the editor without a separate build. .NET/C#
builds and export templates are not installed by this flag.

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
activates a newer verified release. This check deliberately uses the newest
stable Godot release rather than the general dependency freshness delay.

```bash
sudo systemctl status auto-update-godot.timer
sudo systemctl start auto-update-godot.service
sudo journalctl -u auto-update-godot.service -n 100 --no-pager
```

Update failures leave the previously activated version in place and can use
the normal `--notify` targets. Rerunning the saved setup reconciles the same
installation and timer configuration.
