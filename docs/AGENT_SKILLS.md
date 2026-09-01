# Managed agent workflow skills

infra-tools installs concise operational skills for Codex and OpenCode under
the shared `~/.agents/skills` directory. The skills describe VM-specific
commands and boundaries that a general coding agent cannot infer reliably from
the project alone.

## Installed skills

A normal agent-enabled setup that selects Codex or OpenCode receives these
base skills:

| Skill | Use it for |
| --- | --- |
| `infra-tools-agent-operations` | Readiness checks, deliberate terminal-agent updates, maintenance holds, and controller-side credential rotation |
| `infra-tools-agent-workspace` | Isolated branches and worktrees for concurrent tasks |
| `infra-tools-deploy-smoke` | Preflight and layered smoke checks for test deployments |
| `infra-tools-shared-assets` | SMB/SSHFS asset boundaries and Git LFS workflows |
| `infra-tools-vm-triage` | Redacted host diagnostics and support snapshots |

Browser guidance is selected from the resolved setup instead of being included
in the base catalog:

| Skill | Installed browser capabilities |
| --- | --- |
| `infra-tools-playwright-testing` | Managed Playwright only |
| `infra-tools-t3-preview-testing` | T3 Code collaborative preview only |
| `infra-tools-browser-testing` | Both managed Playwright and T3 Code preview |

The combined skill selects Playwright for repeatable VM-origin work when live
collaboration is unnecessary, and selects T3 preview for shared interaction or
client-origin checks. It routes immediately to Playwright when the T3 app is
closed. T3-only guidance treats a closed app or untrusted client certificate as
a browser coverage gap, not a prerequisite that blocks non-browser work.

Other provisioned capabilities add focused skills:

| Skill | Installed with |
| --- | --- |
| `infra-tools-t3code` | T3 Code web service |
| `infra-tools-web-gateway` | T3 Code setup or the Godot web bundle; the skill publishes and verifies managed static snapshots or live forwards |
| `infra-tools-godot-web` | Godot web bundle |

A skill does not install the capability it describes. A setup with neither T3
Code nor managed Playwright receives no browser skill, avoiding instructions
for tools that cannot exist on that VM.

Claude Code does not consume the shared Codex/OpenCode skill location, so a
Claude-only setup receives the agent management command but not this skill set.

## Reconciliation and ownership

Setup copies repository-owned `SKILL.md` files into the target account. A rerun
refreshes files containing `managed-by: infra_tools` and leaves identical files
alone. It removes obsolete infra-tools-managed browser variants when the
selected capability combination changes, while preserving unrelated skills and
user configuration. It refuses symlinked paths, directories owned by another
user, and a same-name skill without the managed marker.

An older VM receives the current base set when its saved setup is rerun from an
updated infra-tools control plane. `infra-tools agent update` updates Codex,
Claude Code, or OpenCode executables; it does not refresh infra-tools or these
skills.

For an explicit `--steps` setup, `install_agent_workflow_skills` installs the
base and selected browser set. The Playwright, T3 Code, and Godot capability
steps reconcile the relevant catalog as well, so capability-only and
custom-step runs still produce appropriate guidance.

## Maintaining the catalog

Skill sources live in `common/agent_skills`. Keep each entrypoint short and
self-contained, with a precise discovery description and only non-obvious VM
behavior. Add a base skill to `BASE_AGENT_SKILL_NAMES` in
`common/agent_steps.py`. Browser variants belong in
`BROWSER_AGENT_SKILL_NAMES` and the capability selector; other capability skill
tuples should extend the base constant so standalone capability setup remains
complete.

Validate changes with the repository tests and the Codex skill validator when
it is available:

```bash
python3 -m unittest tests.test_agent_skills tests.test_t3_agent_skills
python3 -m unittest tests.test_godot_web_host
```

Also run `git diff --check` and verify that every skill retains the
`managed-by: infra_tools` marker before committing.
