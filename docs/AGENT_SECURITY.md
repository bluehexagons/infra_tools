# Agentic coding security

Agent coding machines intentionally balance a useful learning environment with
defense against common prompt-injection, package, and repository attacks. They
are not a malware-analysis sandbox. Treat the VM boundary, its credentials,
and its network access as part of the security design.

## Default and optional postures

| Posture | Linux account | Codex session | Intended use |
| --- | --- | --- | --- |
| Default | Member of `sudo`; password required | Auto-reviewed requests, workspace write access, no default shell network access | Interactive development and learning |
| `--nopasswd` | Unrestricted `NOPASSWD:ALL` on a VM | Same Codex policy as default | Compatibility and convenient non-root setup reruns |
| `--harden-agent` | Removed from `sudo` | Workspace write access, no approval escalation, no default shell network access | CI/CD, disposable evaluation, and less-trusted packages |

`--nopasswd` and `--harden-agent` are mutually exclusive. A newly provisioned
VM temporarily receives the passwordless rule needed for the streamed setup
handoff. Normal setup removes it before completion. Root SSH remains available
for later setup runs and recovery, but SSH password authentication remains
disabled; protect the authorized private key as a root credential.

The hardened flag does not lock the login itself. SSH and an explicitly
configured desktop remain usable, while the coding identity cannot become an
administrator through `sudo`.

## Codex enforcement

When Codex is selected, setup writes root-owned system defaults to:

```text
/etc/codex/config.toml
```

The default policy selects `on-request`, the `auto_review` reviewer, and the
`:workspace` permission profile. These are low-precedence defaults, not
restrictions: users and clients can still select full access, YOLO-like modes,
or another supported profile. T3 Code may continue to request its upstream
full-access default. This preserves an explicit user choice while making direct
Codex sessions safer by default.

`--harden-agent` also writes `/etc/codex/requirements.toml` and selects `never`
within the same workspace boundary. In that mode there is no approval path to
add permissions, login shells are disabled, and Codex native browser/computer
use, app screenshots, remote control, and unmanaged hooks are disallowed.
Package installation or another command that needs network access should fail
rather than gain it through automatic review.

Hardened requirements are constraints, not warning preferences. Returning to
the default posture removes an infra-tools-owned requirements file so all Codex
choices are available again. Administrator-owned defaults and requirements are
preserved in the default posture; hardened setup refuses to replace them, so
organization policy must be merged deliberately.

This policy covers Codex. Other provider CLIs retain their provider-native
permission model. T3 collaborative preview and separately configured MCP
servers are also distinct capabilities; the Codex native browser/computer
restriction does not remove them.

## Accepted convenience boundaries

- Root SSH stays enabled for provisioning, reruns, and recovery. It is key-only,
  restricted by the managed SSH firewall policy, and protected by fail2ban.
- T3 Code's plain HTTP listener remains available for clients that cannot use
  the private CA. Non-loopback access requires a private/non-global source
  allowlist and active UFW. Prefer the printed managed HTTPS URL whenever the
  client can trust the VM CA.
- Provider, Git, and GitHub credentials live under the coding identity. Code
  running as that identity can generally read that identity's files. GitHub
  token redesign and brokerage are outside this phase.
- T3 Code and agent CLIs use their documented vendor distribution/update
  channels. This reduces arbitrary download sources but does not independently
  prove every upstream artifact or transitive dependency.

## Supply-chain work

For unfamiliar packages or unattended builds, prefer a fresh VM and enable the
hardened posture at creation:

```bash
infra-tools setup agent_vm 10.0.0.40 agent \
  --provision-on pve1 \
  --harden-agent \
  --git-access read \
  --no-browser-automation \
  --no-default-web-ports
```

Also use repository-specific credentials with the least practical scope, avoid
mounting personal shares, keep secrets outside the working tree, and restrict
VM egress at the hypervisor or network firewall when packages should not reach
the Internet. Snapshot or reprovision the VM instead of treating a clean Git
status as proof that untrusted install scripts made no persistent changes.

The hardened flag limits OS privilege and Codex shell escalation. It does not
isolate projects from other files owned by the same user, inspect dependency
behavior, constrain every external MCP service, or protect credentials already
available to that UID. Use a disposable identity or VM when those boundaries
matter.

## Related documentation

- [Command-line reference](COMMAND_LINE.md)
- [SSH authentication](SSH.md)
- [T3 Code server](T3_CODE.md)
- [Credentials and agent configuration](CREDENTIALS.md)
- [Agent browser automation](BROWSER_AUTOMATION.md)
