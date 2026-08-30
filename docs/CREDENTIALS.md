# Credentials and agent configuration

This guide explains the credentials and configuration that can be used when
setting up agent tooling on a workstation or VM. The setup model keeps five
concerns separate:

| Concern | What it controls | How it is supplied |
| --- | --- | --- |
| Workspace credentials | Passwords used by services such as the initial Gogs admin, Samba shares, and SMB mounts | `infra-tools credentials set`, or `--credential USERNAME PASSWORD` |
| Git access policy | Whether the target may use Git repositories and whether its intended access is read-only or read-write | `--git-access` |
| GitHub and agent authentication | Secret files installed for `gh`, Codex, Claude Code, or OpenCode | An active-user source, a specified file, or the interactive setup flow |
| Agent configuration | Non-secret settings, instructions, skills, rules, aliases, and extensions | `--agent-config active` |
| Browser website sessions | Credentials and cookies for sites visited through agent browser automation | Not copied by infra-tools; use a task-specific, scoped secret flow |
| Device enrollment | Basic Auth account used to request short-lived provider pairing links | A specified htpasswd file, transient password option, or hidden interactive prompts |

The credentials seeded on a VM are optional. Agent tools can be installed
without authentication, and public HTTPS repositories can be cloned without
authentication. Authentication is needed only when the selected work requires
it, such as a private GitHub repository or an agent account.

## The basic setup model

The `agent_vm`, `agent_workstation`, and `agent_code_vm` profiles default
narrowly to GitHub CLI and Codex. `--agent-tool` values add to those defaults
and accept comma-separated lists; use `--no-agent-tool` to remove a default.
`agent_code_vm` also defaults to read-write Git, active Git/agent auth sources,
T3 Code, private web/RDP source ranges, and T3 pairing. For example:

```bash
infra-tools setup agent_workstation 192.168.0.41 \
  --provision-on ts1 --name agent-1 \
  --image-storage ts1-storage \
  --memory 4G --balloon-min 1G \
  --storage root ts1-storage 32G \
  --agent-tool opencode,gh,codex \
  --git-access read \
  --repo https://github.com/example/project.git \
  --agent-config active
```

This declares that the VM should have the selected tools and a read-only Git
working policy. It does not by itself seed credentials. Add one of the
credential source options below when the VM needs authenticated access.

`--git-access` is a VM/user declaration, not a replacement for provider-side
authorization. The token or account installed on the VM ultimately determines
which repositories it can access. A read-only declaration does not make a
read-write GitHub token read-only.

## Workspace credentials

The workspace credential store is for passwords used by infrastructure
features, not for agent accounts or GitHub authentication:

```bash
infra-tools credentials set workspace-user
infra-tools credentials list
infra-tools credentials remove workspace-user
```

`credentials set` prompts for the password when it is not supplied. The store
is kept in the active workspace at:

```text
~/.config/infra_tools/credentials.json
```

Use the global `--workspace PATH` option when managing a non-default
workspace. The file and its containing directory are created with restrictive
permissions. The store is used by workspace services such as the initial Gogs
administrator, Samba shares, and SMB mounts; it is not read by `gh`, Codex,
Claude Code, or OpenCode setup. When Gogs is enabled, a stored credential whose
username matches the setup username supplies the initial administrator
password. If no match exists, setup generates the password. Reruns preserve an
existing Gogs administrator password rather than rotating it.

The repeatable setup option `--credential USERNAME PASSWORD` saves the same
workspace credential before setup. Prefer `infra-tools credentials set` when
possible because its hidden prompt keeps the password out of shell history and
the process list.

The `--password` setup option is different again: it is the password for the
target account being created or configured. It is used during that operation
and is not a persistent agent credential.

## Selecting agent tools

Use one repeatable or comma-separated `--agent-tool` option to add tools:

```bash
--agent-tool opencode,gh,codex
```

Profile defaults can be disabled explicitly, for example:

```text
--no-agent-tool gh --git-access none --git-auth none --agent-auth none
```

The currently supported tool names are:

| Tool | Auth file supported | Non-secret config supported |
| --- | --- | --- |
| `gh` | Yes, through GitHub auth options | Yes |
| `codex` | Yes | Yes |
| `claude` | Yes | Yes |
| `opencode` | Yes | Yes |

Authentication and configuration are independent. Selecting a tool does not
seed its credentials, and selecting `--agent-config active` does not copy
secret auth files.

## Agent authentication files

The supported authentication payloads seed the target user's canonical
locations when that credential is missing. A staged, current Codex credential
also replaces an existing Codex credential whose metadata definitively reports
that refresh is required:

| Tool | Target path |
| --- | --- |
| `gh` | `~/.config/gh/hosts.yml` |
| `codex` | `~/.codex/auth.json` |
| `claude` | `~/.claude/.credentials.json` |
| `opencode` | `~/.local/share/opencode/auth.json` |

When `active` is selected, these paths are read beneath the active controller
user's home directory, with one important provider-specific exception:
GitHub CLI may keep its token in an operating-system credential store instead
of in `hosts.yml`. In that case infra-tools asks the controller's `gh` command
for the token. A specified file can use any controller-local path, but it is
still installed at the canonical target path.

Credential files are mutable, target-owned state. Codex and other tools may
refresh or rotate them while they run, so an ordinary setup rerun preserves an
existing target credential by default. The narrow exception is a Codex target
with `refresh_required` metadata when the staged source is unambiguously
current and has no freshness warning. The same preservation rule still applies
to an existing selected GitHub host entry and to Claude Code and OpenCode. Use
the explicit `infra-tools agent auth set` command for every other intentional
replacement or rotation.

These are the standard Linux paths used by infra-tools. Vendor settings that
relocate a tool's home or data directory are not discovered by the active
source; use a specified file when the credentials live elsewhere.

The source is always on the controller/orchestration system. The target VM
does not need the corresponding tool installed on the controller in order to
receive a credential file. For example, a controller without Codex installed
can still use `--agent-auth-file codex PATH` to stage a Codex auth file.

### Seed from the active user's configuration

Use the active source when the controller user already has the relevant
configuration in its standard location:

```bash
--git-auth active
--agent-auth active
```

`--git-auth active` is the GitHub-specific form and is normally the clearest
choice when the VM needs private GitHub repositories. It first uses a token in
the selected `hosts.yml` entry. If the entry has no token because `gh` uses an
OS credential store, it runs `gh auth token --hostname github.com` on the
controller and stages the returned token while preserving the selected host's
account name and Git protocol metadata. This requires `gh` to be installed and
already authenticated on the controller; infra-tools does not force GitHub CLI
into insecure plaintext storage.

`--agent-auth active` seeds known credentials for the selected supported
agent tools. Codex, Claude Code, and OpenCode use their standard file-backed
paths; those files must exist. The `gh` selection uses the same `gh auth token`
keyring fallback as `--git-auth active`. No other agent command is run on the
controller to create credentials.

The active user is the invoking user, or the original user when setup is run
through `sudo`. The options are convenience sources, not VM-specific
credentials. In particular, a Codex ChatGPT `auth.json` contains renewable
OAuth state and should not be used concurrently by the controller and several
VMs. Prefer a separately authenticated file or a distinct API key for each VM.
infra-tools reports stale Codex access-token and refresh metadata before
staging, but it cannot make one OAuth session independent merely by copying it.

The high-capability `agent_code_vm` profile selects active GitHub and agent
credential sources automatically. If either identity should be omitted, use
`--git-auth none` and/or `--agent-auth none`. A missing RDP account password or
pairing password is requested with a hidden terminal prompt; an empty pairing
password reuses the account password entered for the target.

Do not combine an active source with its specified-file alternative:

```text
--git-auth active       conflicts with --git-auth-file PATH
--agent-auth active     conflicts with --agent-auth-file TOOL PATH
```

### Seed from specified files

Use a specified file when credentials are kept outside the active user's
standard configuration, when the controller does not have the agent installed,
or when each VM should receive a different provider identity:

```bash
--git-auth-file /run/secrets/agent-1/hosts.yml
--agent-auth-file gh /run/secrets/agent-1/hosts.yml
--agent-auth-file codex /run/secrets/agent-1/codex-auth.json
--agent-auth-file opencode /run/secrets/agent-1/opencode-auth.json
```

`--agent-auth-file` is repeatable and takes the tool name followed by the
controller-local path. For `gh`, the file may be a selected-host `hosts.yml`
or a one-line token, just like `--git-auth-file`. For the other supported
tools it is the tool's auth file. The source basename does not need to be
canonical; the target receives the canonical filename shown above. For
example, `codex-auth.json` becomes `~/.codex/auth.json`.

The source must be a regular, non-symlink file, must not be group- or
world-writable, and must be no larger than 4 MiB. The source is not removed
from the controller. A missing target file is seeded for the target user with
mode `0600`; an existing target file is retained except for the narrow
stale-Codex refresh case described above.

Use `--agent-auth-file gh` as the alternative to `--git-auth`,
`--git-auth-file`, or a GitHub token. Do not supply two GitHub credential
sources, combine `--agent-auth active` with a file for the same tool, or repeat
a tool in `--agent-auth-file`; setup rejects those ambiguous combinations
instead of silently choosing one.

### GitHub file formats

`--git-auth-file` accepts either:

1. a GitHub CLI `hosts.yml` containing the selected host entry, or
2. a one-line GitHub token.

The host is `github.com` by default. `--git-host` selects the host name used by
the GitHub processing, but authenticated GitHub setup currently accepts only
`github.com`. Only the selected host entry is staged. GitHub authentication is
currently the only authenticated Git-host flow; credentials for other Git
hosts can be added later without changing the public-repository flow.

During initial VM setup, a missing selected GitHub host entry is appended to
the target user's existing `gh` hosts file, preserving entries for other hosts.
An existing selected host entry is also retained because `gh` may have updated
its token on the VM.
When the target can authenticate successfully, setup also runs `gh auth
setup-git` for that host so HTTPS Git operations use the GitHub CLI
credential. Setup also fills missing global Git `user.name` and `user.email`
values so terminal and web-interface commits work immediately. It copies only
those two values from the controller user's global Git configuration, not the
complete `.gitconfig`. Existing target values take precedence. When a value is
not configured on the controller, setup derives it from the authenticated
GitHub account and uses GitHub's no-reply address when the account has no
public email.

Do not put tokens directly in a saved setup command, shell history, issue, or
documentation. Prefer a protected file path or the interactive token prompt.

### Portability by tool

Copying an auth file is supported only where the vendor stores usable
credentials in that file. It does not export an operating-system keychain or
hardware-backed credential automatically.

| Tool | Active-source behavior | File-copy guidance |
| --- | --- | --- |
| GitHub CLI (`gh`) | Uses the selected `hosts.yml` token, or asks the installed controller `gh` for `gh auth token` when the token is keyring-backed | `hosts.yml` with a token or a one-line token file works; copying a keyring-only `hosts.yml` is not sufficient |
| Codex | Reads `~/.codex/auth.json` only | Treat ChatGPT auth as renewable per-machine state. Prefer a dedicated file and let that VM write refreshes back. Setup replaces a definitively refresh-required target only from an unambiguously current staged source; do not distribute one active `auth.json` across concurrently running machines. If Codex uses `cli_auth_credentials_store = "keyring"` or `"auto"` and no file exists, configure the file backend and authenticate, or provide a separate auth file |
| Claude Code | Reads `~/.claude/.credentials.json` when that file exists | Linux and Windows use a credentials file, but macOS commonly uses Keychain. A macOS keychain session cannot be made portable by copying this file; use a separately supplied token/file or authenticate on the VM |
| OpenCode | Reads `~/.local/share/opencode/auth.json` when that file exists | The current auth file is plain JSON and is seeded as-is when missing. That layout appears portable, but OpenCode does not provide a general cross-machine portability guarantee, so test the target and use separate files for separate identities |

Codex's documented headless options include device-code login and API-key or
environment-based automation. Claude Code documents `CLAUDE_CODE_OAUTH_TOKEN`,
API-key variables, and `apiKeyHelper` for automation. infra-tools currently
stages credential files; it does not create target environment variables or
secret-manager entries for those alternatives. Configure those mechanisms
manually on the target when they are preferable to copying a file.

For the vendor details behind these behaviors, see the official
[GitHub CLI authentication documentation](https://cli.github.com/manual/gh_auth_login),
[Codex authentication documentation](https://developers.openai.com/codex/auth),
[Codex CI/CD authentication guidance](https://learn.chatgpt.com/docs/auth/ci-cd-auth),
[OpenCode provider authentication documentation](https://opencode.ai/docs/providers/),
and [Claude Code authentication documentation](https://code.claude.com/docs/en/authentication).

## Non-secret agent configuration

Use this option to copy configuration and instructions from the active
controller user:

```bash
--agent-config active
```

This is separate from authentication and does not copy auth files. It may
include a tool setting that selects a credential backend, but it does not make
a keyring-backed credential file appear. The current
configuration sources are:

| Tool | Active configuration copied |
| --- | --- |
| `gh` | `~/.config/gh/config.yml`, `aliases.yml`, and extensions; `hosts.yml` is excluded |
| `codex` | `~/.codex/config.toml`, `AGENTS.md`, `skills`, and `rules` |
| `claude` | `~/.claude/settings.json`, `CLAUDE.md`, `commands`, `agents`, `skills`, and `plugins` |
| `opencode` | The active `~/.config/opencode` directory |

Only selected provider tools receive their corresponding configuration. T3
Code is an interface, not a provider credential source: its headless server
uses the provider credentials already installed for the target user, and its
pairing/session credentials are created and managed on the VM with
`t3code-pair` (or `infra-tools agent web pair HOST USER`) and `t3 auth`.
The infra-tools helpers issue administrative one-time links so the paired app
can manage authorized clients; their temporary bootstrap session is revoked
immediately. The optional protected enrollment portal provides the same flow
without terminal access. Its Basic Auth file is an infra-tools/Nginx secret,
not a T3 or coding-provider credential; see
[DEVICE_PAIRING.md](DEVICE_PAIRING.md).
Missing source files or directories are skipped; `--agent-config active` does
not invent a default configuration for a tool.

The active configuration source uses the same active-user selection described
for active credentials. There is currently no arbitrary config-file option;
use the active configuration layout when this feature is needed.

## Interactive setup

Add `--interactive` when the operator should choose the tools, repositories,
Git access, credential sources, and optional configuration through prompts:

```bash
infra-tools setup workstation_dev 192.168.0.41 \
  --provision-on ts1 --name agent-1 \
  --agent-tool gh --agent-tool codex --agent-tool opencode \
  --interactive
```

Existing command-line values are retained, so the prompts fill in missing
choices rather than replacing explicit options. The flow can ask for:

- a Git host and VM Git access (`none`, `read`, or `read-write`) when Git or
  repositories are selected;
- GitHub auth from no source, the active configuration, a specified file, or a
  hidden token prompt when the selected host is `github.com`;
- an active or specified file for each selected non-GitHub agent auth payload;
- whether to copy active non-secret agent configuration.
- whether to install Playwright browser automation when Codex or OpenCode is selected.
- whether to enable protected T3 device enrollment and, when selected, the
  Basic Auth username plus hidden password confirmation.

The interactive flow requires a terminal on standard input and output. A
non-interactive automation system should use explicit options and protected
file paths instead. Dry-run mode does not prompt for or stage credentials.

## Repositories and Git access

Repositories are cloned on the target VM over HTTPS. Git terminal prompting is
disabled, so a private clone fails clearly instead of waiting for an
unattended password prompt.

| `--git-access` | Intended VM behavior |
| --- | --- |
| `none` | Do not configure persistent Git access; public HTTPS repositories can still be cloned |
| `read` | Allow the setup to use Git for read-only repository work |
| `read-write` | Allow the setup and agent workspace to use Git for read/write work |

A public repository does not need GitHub credentials and can come from any
reachable Git host:

```bash
--git-access read \
--repo https://git.example.net/public/tools.git
```

A private GitHub repository needs all of the relevant pieces: `gh` selected by
an agent profile or explicit tool list, GitHub auth supplied through
`--git-auth`, `--agent-auth` for `gh`, or the interactive flow, an appropriate
`--git-access` value, and a token authorized for that repository. For example,
a per-VM setup can use protected files that are different for each VM:

```bash
--agent-tool gh \
--git-access read \
--git-auth-file /run/secrets/agent-1/github-hosts.yml \
--repo https://github.com/example/private-project.git
```

The Git access setting is not a security boundary by itself. Use provider-side
repository permissions and tokens with the minimum required scope, and use a
different credential file when a VM needs an independent revocation and audit
boundary.

## Rotating and checking credentials

Credentials can be updated after setup without recreating the VM:

```bash
infra-tools agent auth set 192.168.0.41 agent-1 \
  --tool codex \
  --file /run/secrets/agent-1/codex-auth.json

infra-tools agent auth set 192.168.0.41 agent-1 \
  --tool gh \
  --active
```

Use `--interactive` with `agent auth set` when selecting the source or host
interactively. Use status to inspect installation and credential metadata
without printing secret contents:

```bash
infra-tools agent auth status 192.168.0.41 agent-1
infra-tools agent auth status 192.168.0.41 agent-1 --tool codex --json
```

Status can report whether a supported auth file is present, its owner and
permissions, its age, and the `gh` authentication result. For Codex ChatGPT
auth it also reports `last_refresh`, unverified cached access-token issued-at
and expiry dates, refresh-token presence, and a freshness status. It never
displays tokens, account IDs, or file contents. Rotation writes the target file
atomically with restrictive permissions and rejects unsafe source files. For
`gh`, rotation replaces the target `hosts.yml` with the selected host payload.
Unlike setup, `agent auth set` deliberately replaces an existing credential.

## Sharing credentials between VMs

Static provider tokens can be seeded to multiple VMs when a shared identity is
intentional. Each VM gets its own file, but those files represent the same
provider account or token. This means:

- revoking or rotating the token affects every VM using it;
- provider audit logs identify the same identity rather than an individual VM;
- the token's full repository and service scope is available from every VM;
- one compromised VM can expose access intended for the others.

Do not apply that pattern to renewable Codex ChatGPT `auth.json` state. Codex
refreshes and writes the file back, and concurrent copies can diverge or rotate
one another's refresh credentials. Keep one independently authenticated stream
per machine (or serialized job stream), and use a dedicated API key or secret
manager for automation where appropriate.

For independent access, use separate provider tokens or auth files and pass a
different `--git-auth-file` or `--agent-auth-file` for each VM. A common
pattern is a protected per-VM directory such as
`/run/secrets/agent-1/` on the controller, with access restricted to the
operator or provisioning service.

## Security and lifecycle

- Credential source options are used during staging and are not included in
  saved setup commands or ordinary setup summaries.
- Credential payloads are staged for the target setup, transferred with
  restrictive permissions, and removed after processing or failure cleanup.
- Device-pairing htpasswd sources use the same transient staging model. The
  target copy is root-owned and readable by Nginx; its source path and any
  interactively entered password are not saved.
- Auth source files are never deleted or modified by setup.
- Keep source files outside the repository and protect their containing
  directories.
- Use the smallest provider scope that supports the VM's work. Treat a
  read-write token as read-write even if the setup declaration says `read`.
- Ordinary setup preserves target credentials except when it can safely replace
  refresh-required Codex auth with a current staged source.
- Rotate credentials with `agent auth set` when a token expires, a VM changes
  ownership, or a VM is retired. Revoke the provider token as well when it may
  have been exposed.

## Troubleshooting

**A private repository clone fails.** Confirm that `gh` is selected, GitHub
auth was supplied, the selected GitHub host matches the repository, and the
token can read that repository. Check the VM's declared `--git-access` value
and run `agent auth status` without exposing the token.

**An active source is missing.** For Codex, Claude Code, and OpenCode, inspect
the expected active-user paths in the authentication table. The tool may be
using a keyring instead of a file; use the vendor's file-backed mode or
`--agent-auth-file TOOL PATH`. For active `gh`, install/authenticate `gh` on
the controller so infra-tools can retrieve a keyring-backed token, or use
`--git-auth-file PATH`/`--agent-auth-file gh PATH`. A specified file source
does not require the corresponding agent to be installed on the controller.

**A specified source is rejected.** Check that it is a regular file, not a
symlink, not group/world-writable, and smaller than 4 MiB. Use a protected
temporary or secret-management path rather than a repository file.

**The VM has an agent but no account configuration.** Tool installation,
authentication, and non-secret configuration are separate. Add the relevant
auth option and, if needed, `--agent-config active`, then rotate with
`agent auth set` for an existing VM.

**Codex reports an expired authentication token.** Run `infra-tools agent
doctor HOST USER --tool codex --json` or `infra-tools agent auth status HOST
USER --tool codex --json`. If the cached access token is expired and
`last_refresh` is overdue, rerun setup with a current staged Codex source,
authenticate that VM independently, or explicitly replace it with `agent auth
set`. Setup replaces the target only when its metadata says refresh is required
and the staged source is unambiguously current.

**An agent installer reports permission denied under `~/.local/bin`.** Current
setup repairs ownership of the target user's `.local` tree before running
Codex, Claude Code, or OpenCode installers. Rerun the saved setup command; no
manual recursive ownership command should be necessary.

## Related documentation

- [Command-line reference](COMMAND_LINE.md) — complete setup and agent
  command options.
- [Installation guide](INSTALLATION.md) — setup flow and prerequisites.
- [Workstations](WORKSTATIONS.md) — workstation and VM examples.
- [Agent browser automation](BROWSER_AUTOMATION.md) — MCP setup, isolated
  browser sessions, site credentials, and security boundaries.
- [Protected device pairing](DEVICE_PAIRING.md) — Basic Auth enrollment,
  provider-native sessions, rotation, and removal.
- [System administration](SYSADMIN.md) — target access and operational
  guidance.
