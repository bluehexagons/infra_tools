# Agent VM Workspaces and Credentials

Status: implemented in the current release. Authenticated non-GitHub
providers and offline snapshot mode remain future work.

This project makes it straightforward to provision a Debian VM for agentic
development while keeping tool selection, Git access, repository setup, and
credential transfer explicit. It replaces the current bundled agent-suite
model with a small set of deliberate setup choices. This is an intentional
CLI redesign: old suite flags and compatibility aliases are not retained.

## Problem

The current agent-host path combines several concerns:

- an agent suite selects multiple tools and a shared package bundle;
- separate flags select configuration and credential copying;
- repositories are cloned on the orchestration host before being uploaded;
- credential copying assumes the controller user's known tool directories; and
- Git access is configured as a consequence of copying GitHub CLI state.

That is workable when the controller is also the user's development machine,
but it is a poor fit for a control system that only manages VMs. The controller
may not have GitHub CLI, Codex, or OpenCode installed. The target may need
access to only a deliberately limited set of repositories. An operator may
also want to enter or select credentials during setup without putting secret
values in a saved command.

## Goals

- Install exactly the agent tools explicitly selected by the operator.
- Treat Git credentials and their access level as a VM/user-level policy.
- Let repeated repository declarations inherit that VM-level Git policy.
- Clone public HTTPS repositories from any Git host without requiring
  credentials or a Git-host-specific tool.
- Clone private repositories on the target when target credentials are used,
  so the controller does not need the corresponding Git tooling or access.
- Support credentials from either the active user's known configuration or an
  explicitly supplied file in non-interactive setup.
- Provide an interactive setup flow for selecting tools, Git access, agent
  credentials, and repositories.
- Keep secrets out of process arguments, saved setup commands, logs, and
  normal diagnostic output.
- Preserve existing workspace and repository safety behavior: restrictive
  permissions, atomic writes, symlink checks, and no overwrite of existing
  agent work.

## Non-goals

- A general secret-provider abstraction or plugin matrix.
- Profile or manifest files for the setup request. Saved setup commands remain
  the reusable non-secret profile mechanism.
- Automatically installing every supported agent or development runtime.
- Authenticated non-GitHub Git-host integrations in the first release. The
  repository model must remain host-neutral so those adapters can be added
  later.
- Copying the controller's complete `~/.ssh` directory.
- Treating a repository list as a substitute for GitHub token scoping. The
  credential itself remains the security boundary.

## Design decisions

### Explicit tools

Remove `agent_suite` and its `terminal`, `desktop`, and `full` presets. Agent
installation should use one repeatable option with a closed set of choices:

```text
--agent-tool gh
--agent-tool codex
--agent-tool opencode
```

Other supported tools may be selected in the same way. Selecting one tool
installs that tool and only the dependencies required by its installer. It
does not select other agents, language runtimes, desktop applications, or a
large coding-utility bundle. The current common coding-tool baseline is not
installed implicitly; optional packages remain available through the normal
package options.

The implementation should use one tool registry. A tool entry owns its
installer, target configuration paths, credential path/format, authentication
check, and any Git integration. This prevents each new tool from adding
another set of conditionals to setup and payload handling.

### VM-level Git access

Git access is selected once for the target Unix user, not repeated for every
repository:

```text
none       Do not install persistent Git credentials.
read       Declare that the VM should use a read-only Git grant.
read-write Declare that the VM should use a read/write Git grant.
```

`--repo` declarations do not require a read/write suffix. They identify
repositories to prepare in the target user's workspace and inherit the
target's Git policy. Repository declarations may later gain optional path,
branch, or revision fields, but access level remains a VM-level choice.

The policy is an operator declaration, not a local enforcement mechanism. A
read-only VM configured with an over-scoped token can still write. The
provider-side token or App grant is the actual security boundary, and setup
must make that distinction clear in summaries and diagnostics.

Repository URLs are host-neutral. Public HTTPS repositories on GitHub,
GitLab, Codeberg, self-hosted Git servers, or another reachable Git host can
be prepared with `git-access none`; no credential adapter is needed. The first
authenticated integration is GitHub: HTTPS Git credentials are represented by
the selected GitHub CLI identity and configured with `gh auth setup-git`.

For private GitHub repositories, `gh` must be explicitly selected as an agent
tool. Selecting Git credentials must not silently install GitHub CLI. The
controller still does not need `gh`; the target does. Authenticated
non-GitHub hosts are a later provider-adapter project, not a reason to limit
public repository support now.

The first authenticated GitHub implementation should support a fine-grained
token or equivalent `hosts.yml` identity scoped to the repositories that the
VM is allowed to use. GitHub App credential lifecycle is deferred until its
target format, renewal, and diagnostic behavior are specified.

The setup can verify that the declared repositories are reachable and report
which access policy was requested. It cannot locally prove that a token's
provider-side repository scope is correct. The operator remains responsible
for supplying a token whose scope matches the VM policy.

One `gh` identity is effectively host-wide for a Unix user. If two sets of
repositories require materially different trust levels, use separate VMs or
Unix users. Per-repository credential helpers may be considered later for
Git-only operations, but they do not provide equivalent isolation for `gh`
API operations available to the agent.

### Repository preparation

The normal repository path should be target-side cloning:

1. Install Git and the explicitly selected agent tools.
2. Install and validate the requested GitHub credentials, if private GitHub
   repositories are declared.
3. If private GitHub repositories are declared, configure HTTPS Git
   authentication through `gh`.
4. Clone each declared HTTPS repository into `~/repos/<name>`.
5. Preserve the remote so the agent can fetch or push according to the
   declared VM policy.

Every clone must set `GIT_TERMINAL_PROMPT=0`. Public repositories must work
without a credential; a private repository with no usable credential must
fail clearly instead of hanging or prompting unexpectedly.

This permits a controller with no agent tools and no GitHub account to create a
private-repository VM. It also avoids transferring private source through a
controller-side cache when the target can safely fetch it directly.

A separate snapshot mode may be added for intentionally offline targets. In
that mode the controller stages source, the target receives no Git credential,
and the resulting workspace is explicitly not expected to fetch or push.
Snapshot mode must not be the implicit behavior for a normal `--repo` request.

Repository URLs must reject embedded credentials and, in the first release,
SSH/scp-style URLs that bypass the HTTPS GitHub path. Repository names,
optional checkout paths, revisions, and duplicate destinations must be
validated on the target as well as on the controller.

Existing target repositories remain protected from overwrite. If a declared
repository already exists, setup verifies its identity and remote without
fetching, resetting, or overwriting agent work. A failed clone or credential
preflight must fail the requested workspace setup rather than silently
producing a VM missing one of its declared repositories.

### Two non-interactive credential inputs

Non-interactive setup has only two credential source choices:

1. **Active user configuration**: read the known configuration for the user
   invoking infra-tools. When invoked through `sudo`, resolve the original
   active user rather than accidentally reading root's home directory.
2. **Specified file**: read the credential payload from a path supplied by the
   operator or an external secret-mount mechanism.

The controller does not need the corresponding executable installed. It reads
the known file format directly and transfers the resulting payload over the
existing authenticated setup connection.

Tool-specific files remain explicit and allowlisted:

| Tool | Active-user source | Target destination |
| --- | --- | --- |
| GitHub CLI | selected host entry in `~/.config/gh/hosts.yml` | `~/.config/gh/hosts.yml` |
| Codex | `~/.codex/auth.json` | `~/.codex/auth.json` |
| OpenCode | `~/.local/share/opencode/auth.json` | `~/.local/share/opencode/auth.json` |

For GitHub, the operator must select a host, defaulting explicitly to
`github.com`. Active-user setup copies only that host entry; it must not copy
credentials for every host in a multi-host `hosts.yml`. A specified file must
either contain one selected-host entry or be a plain GitHub token file in the
format documented by the command. The setup flow should configure HTTPS Git
without requiring the operator to hand-edit GitHub CLI YAML.

Specified source paths must be validated as regular files, must not be
symlinks, and must meet the documented ownership and permission policy. The
controller may read them directly; it must not invoke `gh`, Codex, OpenCode,
or another agent executable to discover credentials.

Credential source selection is a one-time input to a setup or auth-rotation
operation. It may exist in the transient runtime configuration, but it is not
written to the persisted `SetupConfig` representation or saved setup command.
Saved configuration contains tools, Git policy, and repository declarations; a
rerun preserves existing credentials unless an explicit auth operation is
requested. The target path must be owned by the selected setup user and the
payload format must be valid.

### Non-secret agent configuration

Non-secret instructions, skills, aliases, and tool configuration remain
separate from credentials. If they are retained, copying them must be an
explicit active-user operation such as `--agent-config active`; selecting a
credential source must never imply copying configuration. The initial design
does not add a second arbitrary configuration-file source. Repository files
such as `AGENTS.md` remain the preferred way to provide project-specific
instructions.

### Interactive setup

The setup command should offer an explicit interactive mode, for example:

```text
infra-tools setup server_dev 10.0.0.10 agent --interactive
```

After the target and machine details are known, the flow presents choices in
this order:

1. Select the agent tools to install.
2. Add repositories, accepting public HTTPS repositories from any reachable
   Git host, with optional checkout path and revision choices.
3. For private GitHub repositories, select the GitHub host and Git access:
   none, read-only, or read-write.
4. Select GitHub credentials: skip, use the active user's selected-host
   configuration, choose a credential file, or enter a GitHub token.
5. For each selected agent, choose whether to copy active-user non-secret
   configuration and whether to authenticate it from the active configuration,
   a credential file, or supported interactive input.
6. Display a complete redacted plan and require confirmation.

The interactive flow produces the same validated `SetupConfig` and saved setup
command as non-interactive setup. It does not create a second provisioning
engine or a profile file. Secret values and credential source choices are used
only for this operation and are never placed in the saved command. The flow
must fail clearly when stdin is not a TTY; `--dry-run` must not prompt for or
stage secret material.

The prompts should distinguish these states:

- tool not selected;
- tool selected but intentionally unauthenticated;
- credential source selected but file absent or invalid;
- credential installed and authentication check passed; and
- credential installed but authentication could not be verified.

### Credential rotation

Add a focused remote command for changing credentials without rebuilding the
VM, such as:

```text
infra-tools agent auth set HOST USER --tool gh --file PATH
infra-tools agent auth set HOST USER --tool codex --file PATH
infra-tools agent auth set HOST USER --tool opencode --file PATH
```

For GitHub, the command also accepts an explicit Git host and performs the
same one-host filtering as initial setup. `PATH` is a controller-local source
path, never a target path or a value passed through the remote command line.
The same command should offer an interactive selection of active-user config,
file path, or supported token entry. It must not require the controller to
have the target tool installed. Replacement must be atomic and preserve the
previous credential if validation or transfer fails. `agent auth status` should
report only presence, ownership, mode, age, installation state, and
authentication result; never credential contents.

## Proposed command shape

A normal public-repository setup should read approximately as follows:

```bash
infra-tools setup server_dev 10.0.0.10 agent \
  --agent-tool codex \
  --agent-tool opencode \
  --repo https://github.com/acme/application.git \
  --repo https://gitlab.com/acme/documentation.git
```

For private GitHub repositories, GitHub CLI and a one-host credential source
are explicit:

```bash
infra-tools setup server_dev 10.0.0.10 agent \
  --agent-tool gh \
  --agent-tool codex \
  --git-access read \
  --git-host github.com \
  --git-auth active \
  --repo https://github.com/acme/application.git
```

An operator using mounted secret files could instead select an individual
GitHub credential file:

```bash
infra-tools setup server_dev 10.0.0.10 agent \
  --agent-tool gh \
  --agent-tool codex \
  --git-access read \
  --git-host github.com \
  --git-auth-file /run/secrets/github-hosts.yml \
  --agent-auth-file codex /run/secrets/codex-auth.json \
  --repo https://github.com/acme/application.git
```

The exact flag names can be finalized during implementation, but the public
model should remain this small: explicit tools, one VM-level Git policy,
optional host-neutral repositories, GitHub authentication as the first
provider-specific integration, active-user configuration or specified files,
and an interactive alternative. Credential source options are operation-only
and are omitted from saved commands.

## Implementation phases

### Phase 1: Configuration model and explicit tools

- Remove `AGENT_SUITES`, `agent_suite`, and suite expansion from configuration.
- Replace individual suite-derived behavior with repeatable explicit tool
  selection and a tool registry.
- Remove the implicit common coding-tool baseline; keep only required tool
  dependencies and expose optional packages through normal package options.
- Define a host-neutral repository declaration and a non-persisted credential
  input model separate from saved `SetupConfig`.
- Update command help, saved-command serialization, summaries, completion,
  and documentation.

### Phase 2: VM-level Git credentials and target-side repositories

- Add the VM-level Git policy and credential configuration.
- Implement public HTTPS repository cloning on the target for any reachable
  Git host without invoking the controller's agent tools.
- Implement one-host GitHub credential staging without invoking the
  controller's `gh`, and require target-side `gh` for private GitHub access.
- Configure HTTPS Git on the target through `gh auth setup-git` when private
  GitHub access is requested.
- Move normal `--repo` preparation to the target after credentials are ready
  when private repositories are requested.
- Make failed setup cleanup cover upload, extraction, and remote-step
  interruption, not only the normal remote `finally` path.
- Preserve safe destination checks, collision behavior, and private cache
  cleanup for any retained snapshot path.

### Phase 3: Interactive setup

- Add the guided selection and prompt flow.
- Reuse the normal parser, validators, setup plan, confirmation, and saved
  command generation.
- Ensure the redacted plan clearly shows tools, Git policy, credential
  presence/source category, repository hosts, and repository declarations.
- Reject interactive mode without a TTY and ensure dry-run never reads or
  stages secret material.

### Phase 4: Credential rotation and diagnostics

- Add `agent auth set` and `agent auth status`.
- Add post-setup checks for tool availability, credential permissions, Git
  remote access, and each declared repository.
- Add explicit snapshot mode only if an offline workflow requires it.

Authenticated providers other than GitHub should be a later adapter project;
they must not change the host-neutral public repository contract.

## Security requirements

- Never accept secret values as ordinary command-line arguments.
- Do not put credential file contents or tokens in `SetupConfig`, saved
  commands, credential source paths, remote argument files, logs, notifications,
  or exceptions.
- Validate source files as regular, non-symlinked files with documented
  ownership, permissions, and size limits; reject symlinked secret
  destinations.
- Use atomic target writes, mode `0600`, and ownership of the selected Unix
  user.
- Remove temporary uploaded credential payloads after successful processing,
  step failure, extraction failure, and transport interruption where cleanup
  is still possible.
- Do not copy arbitrary SSH configuration or private keys.
- Make the requested Git policy visible before confirmation.
- Treat the credential's provider-side repository scope as the authoritative
  access control; repository declarations are not authorization grants.
- Set `GIT_TERMINAL_PROMPT=0` for all unattended repository operations.
- Preserve existing repositories and credentials unless the operator invokes
  an explicit replacement or removal operation.

## Acceptance criteria

- A setup can install only `gh`, Codex, and OpenCode without selecting a suite
  or installing unrelated agents and runtimes.
- A controller without `gh`, Codex, or OpenCode can provision public HTTPS
  repositories from any reachable Git host.
- A controller without `gh`, Codex, or OpenCode can provision private GitHub
  repositories using explicitly supplied or active-user credential files;
  `gh` is installed only on the target when explicitly selected.
- Git access is selected once for the VM/user and applies to all declared
  repositories unless snapshot mode is explicitly requested.
- Private repositories are cloned on the target after credentials are
  installed; the controller does not need repository access for this path.
- Public repositories do not require GitHub CLI or any credential source.
- Authenticated non-GitHub hosts are clearly reported as unsupported rather
  than being treated as GitHub credentials.
- The interactive flow can complete the same setup without exposing secrets in
  the generated or saved command.
- Saved setup commands contain no credential source options and reruns do not
  replace credentials implicitly.
- Credential rotation works without reinstalling tools or overwriting agent
  repositories.
- Tests prove public clones on multiple hosts, missing files, invalid formats,
  multi-host GitHub filtering, unsafe permissions, failed authentication,
  failed repository clones, existing-workspace preservation, and interrupted
  payload cleanup.
- `agent auth status` and setup summaries never expose credential contents or
  repository file contents.

## Related implementation evidence

- `lib/config.py`
- `lib/arg_parser.py`
- `lib/setup_common.py`
- `common/agent_steps.py`
- `lib/agent_cli.py`
- `lib/credentials.py`
- `docs/COMMAND_LINE.md`
- `docs/plans/AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md`
