# Agent VM Setup

Status: first implementation in progress.

Goal: make it easy to provision a disposable, long-lived VM that is ready for AI
agents to work on git repositories with the same tools and credentials as the
local operator intentionally selected.

## Current Command Shape

```bash
infra_tools setup server_dev 10.0.0.10 agentuser \
  --gh \
  --opencode \
  --copy-keys \
  --copy-config \
  --repo https://github.com/user/my_codebase.git
```

`--repo` is repeatable. Repositories are cloned locally, included in the normal
setup tarball, and installed on the target under `/home/<user>/repos/<repo>`.

## Implemented First Cut

- `server_dev` now defaults to `--machine vm`; use `--machine unprivileged` for
  the LXC compatibility path.
- `--gh` installs GitHub CLI from GitHub's Debian apt repository.
- `--opencode` installs OpenCode with the official installer as the setup user
  and adds likely user-local bin directories to `.bashrc`.
- `--copy-config` stages config for tools selected in the same command.
- `--copy-keys` stages credentials for tools selected in the same command.
- Copied GitHub CLI credentials are used to run `gh auth setup-git` for the
  setup user when `gh auth status` validates successfully.
- `--repo` clones locally using the existing git cache/upload flow and copies
  uploaded repos into `/home/<user>/repos` on the target.
- Existing repo destinations are skipped to avoid destroying uncommitted agent
  work on a long-lived VM.

## Credential And Config Sources

Tool-scoped copy avoids accidentally copying credentials for tools that were not
requested.

| Tool | `--copy-config` | `--copy-keys` |
|------|-----------------|---------------|
| GitHub CLI | `~/.config/gh/config.yml`, `aliases.yml`, `extensions/` | `~/.config/gh/hosts.yml`; also wires git HTTPS auth through `gh` when auth validates |
| OpenCode | `~/.config/opencode/` | `~/.local/share/opencode/auth.json` |

OpenCode config files can themselves reference secrets or contain inline API
keys. This implementation copies the requested config as-is and treats
`auth.json` as the standard separated credential store.

## Security Notes

- Secrets are never added to the saved setup command; only the boolean copy flags
  are cached.
- Staged credential payloads live only in the local temporary setup directory and
  the root-owned remote `/opt/infra_tools` setup bundle during setup.
- Remote credential files are installed with mode `0600` and owned by the setup
  user.
- The initial transport still relies on the existing root SSH setup channel. If
  the root channel is compromised, copied credentials are compromised too.

## Open Questions

- Interactive fallback: how should setup prompt for missing credentials when the
  local files are absent, and should prompts write local state or only the remote
  target?
- Repository refresh policy: should there be a `--repo-overwrite` or
  `--repo-update` mode for reruns, or should updates always be manual inside the
  VM?
- GitHub token scope: should setup verify `gh auth status` and required scopes
  before copying `hosts.yml`?
- OpenCode provider coverage: should `--copy-keys` also discover provider env
  vars and secret files referenced by config, or only copy `auth.json`?
- VM lockdown: what extra host/guest isolation should be enabled by default for
  agent VMs beyond the existing server hardening steps?
