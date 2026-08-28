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
| `infra-tools-browser-testing` | Choosing collaborative T3 preview or the optional VM-local Playwright fallback |
| `infra-tools-deploy-smoke` | Preflight and layered smoke checks for test deployments |
| `infra-tools-shared-assets` | SMB/SSHFS asset boundaries and Git LFS workflows |
| `infra-tools-vm-triage` | Redacted host diagnostics and support snapshots |

Provisioned capabilities add focused skills:

| Skill | Installed with |
| --- | --- |
| `infra-tools-t3code` | T3 Code web service |
| `infra-tools-web-gateway` | T3 Code setup or the Godot web bundle; the skill verifies that `infra-web` was provisioned before use |
| `infra-tools-godot-web` | Godot web bundle |

The browser-testing skill is useful even when Playwright is absent: it tells an
agent to prefer a collaborative preview when attached and to verify the local
browser capability before relying on it. A skill does not install the
capability it describes.

Claude Code does not consume the shared Codex/OpenCode skill location, so a
Claude-only setup receives the agent management command but not this skill set.

## Reconciliation and ownership

Setup copies repository-owned `SKILL.md` files into the target account. A rerun
refreshes files containing `managed-by: infra_tools` and leaves identical files
alone. It refuses symlinked paths, directories owned by another user, and a
same-name skill without the managed marker. Removing a tool or capability does
not delete skills or other user configuration.

An older VM receives the current base set when its saved setup is rerun from an
updated infra-tools control plane. `infra-tools agent update` updates Codex,
Claude Code, or OpenCode executables; it does not refresh infra-tools or these
skills.

For an explicit `--steps` setup, `install_agent_workflow_skills` installs the
base set. Capability setup functions continue to install their own focused
skills.

## Maintaining the catalog

Skill sources live in `common/agent_skills`. Keep each entrypoint short and
self-contained, with a precise discovery description and only non-obvious VM
behavior. Add a base skill to `BASE_AGENT_SKILL_NAMES` in
`common/agent_steps.py`; capability skills belong with the owning setup module.

Validate changes with the repository tests and the Codex skill validator when
it is available:

```bash
python3 -m unittest tests.test_agent_skills tests.test_t3_agent_skills
python3 -m unittest tests.test_godot_web_host
```

Also run `git diff --check` and verify that every skill retains the
`managed-by: infra_tools` marker before committing.
