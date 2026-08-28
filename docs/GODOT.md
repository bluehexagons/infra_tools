# Godot Engine

Use `--godot` with any setup profile to install the newest stable standard
Godot Engine release. The installer resolves the engine version at run time;
the `v2.0.0` infra-tools release therefore does not pin a Godot version in its
operator contract.

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
installs `infra-web` plus the `godot-web-publish` compatibility command
system-wide. A project with a `Web` export preset can be exported and activated
without writing a game-specific service or Nginx configuration:

```bash
cd ~/repos/my-game
infra-web publish godot
# Use another preset or create a debug export when needed:
infra-web publish godot my-game --preset "Web Threads" --debug
```

The resulting URL is
`https://HOST:8443/games/USERNAME/my-game/`. The host sends the secure-context
and cross-origin isolation headers required by threaded and web GDExtension
exports:

```text
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

The same endpoint works for Godot's default single-threaded exports. The
publisher derives a URL-safe name from `application/config/name` when a name is
not supplied, creates deterministic gzip copies of `.wasm` and `.pck` files,
and updates a per-user game catalog. Nginx serves those precompressed files
when the browser accepts gzip. Published games are replaced only after Godot
completes a new export, with a per-game lock so unrelated games may publish in
parallel without conflicting updates. A failed build does not remove the last
working copy.

Use the same utility for inspection and cleanup:

```bash
infra-web list
infra-web url my-game
infra-web doctor my-game
infra-web remove my-game --yes
```

`doctor` verifies trusted HTTPS, the secure-context and cross-origin isolation
headers, and the `application/wasm` content type. `--json` is available on
publish, list, and doctor for agent automation. `--open` opens a successful
publication in the user's default browser. Treat the URL returned by
`infra-web` as authoritative: static games are paths behind the shared Nginx
HTTPS listener, not processes bound to game-specific ports.

### Live HTTPS forwarding

Static game exports share port 8443 and do not consume one port per game. For a
live development server, use the supervised preview lifecycle:

```bash
sudo infra-web preview start my-preview --project . --profile godot -- \
  my-preview-server --host '{host}' --port '{port}'

infra-web preview list
infra-web doctor my-preview
sudo infra-web preview stop my-preview
```

When another process manager already owns the service, bind it to a loopback
address and register a low-level managed HTTPS listener:

```bash
# In one shell, the application listens only inside the VM.
my-preview-server --host 127.0.0.1 --port 3000

# In another shell, allocate HTTPS and apply Godot's required headers.
sudo infra-web forward add my-preview \
  --listen auto \
  --to 127.0.0.1:3000 \
  --profile godot

infra-web forward list
infra-web doctor my-preview
sudo infra-web forward remove my-preview
```

See [Internal HTTPS sites and live previews](INTERNAL_WEB.md) for static-site
publishing, automatic Vite previews, service lifecycle, health waits, logs,
cleanup, and certificate trust.

The configured account already has the VM setup's non-interactive sudo access;
preview and forward mutations require it, while publication and inspection do
not. `infra-web` allocates TCP 8444–8999 by default, restricts upstreams to
unprivileged loopback ports, reuses the managed certificate, enables WebSocket
proxying, inherits the saved `--access-source` policy, and reconciles
comment-tagged UFW rules. It validates Nginx before a reload and restores the
previous generated configuration and state when a mutation fails. Raw Nginx
directives, non-loopback targets, and source-policy overrides are not accepted.
The `--to` port is private HTTP on loopback; the allocated `--listen` port is
public HTTPS on Nginx, and only that listener is opened through the managed
firewall policy.

If a current Let's Encrypt certificate already exists for a configured DNS
name, the origin reuses it. Otherwise setup creates a VM-local certificate
authority, installs it into the VM's system trust store, and issues a server
certificate covering the configured identities, active non-loopback interface
addresses, system hostname, and loopback names. It also enrolls the CA in each
managed user's Chromium NSS database, so Playwright and Chromium-based agents
on the VM trust the same origin as system tools. A browser on another computer
must trust that VM CA once; a publicly trusted certificate cannot be issued
automatically for a private IP or an unowned internal hostname. Setup prints
the CA file fingerprint, and the user-readable certificate is available on the
VM at:

```text
/srv/infra-tools/web/infra-tools-ca.crt
```

Run `infra-web ca` to print the active CA path and SHA-256 fingerprint. When an
existing publicly trusted certificate is in use, the command reports that no
private CA enrollment is required. Never use an insecure TLS bypass for an
agent or browser check.

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

When Codex or OpenCode is selected on the target, the web bundle also installs
the `infra-tools-godot-web` and `infra-tools-web-gateway` skills under
`~/.agents/skills`. Both agents discover that shared standard location. The
skills teach agents to publish and diagnose the managed origin, use loopback
for live servers, and avoid direct Nginx/UFW edits or TLS verification bypasses.
They contain no credentials and are not installed for a profile that selects
neither agent.

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
