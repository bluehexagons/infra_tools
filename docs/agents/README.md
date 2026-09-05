# Agent systems

This is the operator starting point for infra-tools-managed coding VMs and
workstations. It groups the guides needed to choose a profile, set a security
posture, provide credentials, and verify the resulting environment.

It does not replace the repository
[contributor and coding-agent guide](contributing/README.md). That guide
applies when changing this repository; this page applies when operating a
managed machine.

## Choose a task

| I need to… | Start here | Then use |
| --- | --- | --- |
| Choose a headless or graphical coding profile | [Workstations](../WORKSTATIONS.md) | [Command-line agent flags](../COMMAND_LINE.md#agent-host-flags) |
| Choose default, passwordless-sudo, or hardened operation | [Agentic coding security](../AGENT_SECURITY.md) | [Workstations](../WORKSTATIONS.md) |
| Choose a credential workflow | [Credentials overview](../CREDENTIALS.md) | [SSH authentication](../SSH.md) |
| Seed, rotate, or recover coding-agent auth | [Agent authentication](../AGENT_AUTHENTICATION.md) | [Credentials overview](../CREDENTIALS.md) |
| Configure GitHub or self-hosted Git access | [Git access](../GIT_ACCESS.md) | [Credentials overview](../CREDENTIALS.md) |
| Use managed browser testing | [Agent browser automation](../BROWSER_AUTOMATION.md) | [Managed workflow skills](../AGENT_SKILLS.md) |
| Install or operate T3 Code | [T3 Code server](../T3_CODE.md) | [Agent browser automation](../BROWSER_AUTOMATION.md) |
| Understand installed skills and capability routing | [Managed workflow skills](../AGENT_SKILLS.md) | [Command-line agent flags](../COMMAND_LINE.md#agent-host-flags) |
| Build or publish a Godot web project | [Godot Engine](../GODOT.md) | [Internal HTTPS sites](../INTERNAL_WEB.md) |

## Day-two checks

Run these commands from the controller after setup or when an agent service
needs attention:

```bash
infra-tools agent doctor HOST USER
infra-tools agent update HOST USER
infra-tools agent maintenance status HOST USER
```

Use `agent doctor` to verify the managed agent capability. Use `agent update`
only for a deliberate terminal-agent upgrade. Maintenance holds are for
protecting active work from scheduled host maintenance; see
[recurring maintenance](../MAINTENANCE.md#agent-maintenance-holds).

## Boundaries worth checking first

| Concern | Guide |
| --- | --- |
| Privilege, sandboxing, prompt injection, and supply chain | [Agentic coding security](../AGENT_SECURITY.md) |
| Credential scope, copying, rotation, and lifecycle | [Agent authentication](../AGENT_AUTHENTICATION.md) |
| Browser access and private-network trust | [Agent browser automation](../BROWSER_AUTOMATION.md) |
| Host capability differences | [Machine types](../MACHINE_TYPES.md) |
| Managed worktrees and deployment smoke checks | [Managed workflow skills](../AGENT_SKILLS.md) |

For non-agent host operations, return to the
[documentation index](../README.md) or [quick reference](../QUICK_REFERENCE.md).
