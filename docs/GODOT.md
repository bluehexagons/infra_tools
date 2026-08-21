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
| `web` | Version-matched web export templates plus a managed HTTPS publishing origin for regular, single-threaded, threaded, and GDExtension-enabled debug/release exports |
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

### Managed HTTPS web hosting

The web bundle also installs an isolated Nginx origin on TCP 8443. Setup opens
that port through the same UFW and `--access-source` policy as other managed
web ports, creates a publishing directory for the configured account, and
installs `godot-web-publish` system-wide. A project with a `Web` export preset
can be exported and activated without writing a game-specific service or
Nginx configuration:

```bash
cd ~/repos/my-game
godot-web-publish my-game
# Use another preset or create a debug export when needed:
godot-web-publish my-game --preset "Web Threads" --debug
```

The resulting URL is
`https://HOST:8443/games/USERNAME/my-game/`. The host sends the secure-context
and cross-origin isolation headers required by threaded and web GDExtension
exports:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

The same endpoint works for Godot's default single-threaded exports. Published
games are replaced only after Godot completes a new export, so a failed build
does not remove the last working copy. Agents and interactive users share the
same command and user-owned publishing root.

If a current Let's Encrypt certificate already exists for a configured DNS
name, the origin reuses it. Otherwise setup creates a VM-local certificate
authority, installs it into the VM's system trust store, and issues a server
certificate covering the setup host, configured system hostname, and loopback
names. Browsers and agents running inside the VM therefore trust the origin
without per-game configuration. A browser on another computer must trust that
VM CA once; a publicly trusted certificate cannot be issued automatically for
a private IP or an unowned internal hostname. Setup prints the CA file
fingerprint, and the certificate is available on the VM at:

```text
/var/lib/infra_tools/internal-web-pki/ca.crt
```

The private CA key remains root-only. Re-running setup preserves the CA and
renews the server certificate when its names change or it approaches expiry.
The weekly Godot maintenance run also reconciles the certificate, Nginx site,
publishing users, and export templates. No game-specific TLS renewal job is
needed.

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
when exported games need browser smoke tests. The origin and publisher are
system-wide, so browser-capable agents can test the same URL shown after
publishing without a separate server process.

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
