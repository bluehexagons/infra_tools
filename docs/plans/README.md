# Planning and Issue Index

Status: current portfolio index. This file organizes active project plans,
audit inputs, and open GitHub issues without replacing the detailed scope in
the [project roadmap](ROADMAP.md) or the
[issue triage](GITHUB_ISSUE_TRIAGE_2026-08-17.md).

## Planning model

- **P0** is the reliability foundation and should block dependent mutation
  work.
- **P1** extends that foundation into shared deployment and audit workflows.
- **P2** adds recovery and broader safe-apply workflows after their underlying
  state and verification contracts exist.
- **P3** improves extensibility and release quality once the core lifecycle is
  dependable.
- **Unscheduled** work needs a project brief or an explicit roadmap slot before
  implementation starts.
- **Reference** documents preserve evidence or completed review decisions; they
  are not independent implementation queues.

The roadmap owns priority. The issue triage owns issue-to-implementation
evidence. A detailed project plan owns delivery sequence and acceptance
criteria.

## Project portfolio

| Project | State | Priority | Issue alignment | Canonical plan and next boundary |
| --- | --- | --- | --- | --- |
| Transactional execution and state | Active; ready for the next slice | P0 | [#97](https://github.com/bluehexagons/infra_tools/issues/97) | [Transactional execution](TRANSACTIONAL_EXECUTION.md): finish the command-caller inventory, decide the existing transaction framework's fate, and define durable operation markers. |
| Manifest deployment platform | Queued behind P0 | P1 | [#63](https://github.com/bluehexagons/infra_tools/issues/63) and the remaining deployment scope of [#97](https://github.com/bluehexagons/infra_tools/issues/97) | Implement [deploy secrets](DEPLOY_SECRETS.md), transactional activation, then [CI/CD manifest reuse](CICD_MANIFEST_REUSE.md). |
| Plan, audit, and drift detection | Active in domain-specific slices | P1 | [#58](https://github.com/bluehexagons/infra_tools/issues/58), [#38](https://github.com/bluehexagons/infra_tools/issues/38), and part of [#97](https://github.com/bluehexagons/infra_tools/issues/97) | [Roadmap](ROADMAP.md), informed by the Proxmox, agent-host, and desktop audit documents below. Define one stable observation/result contract before adding more domain commands. |
| Interactive orchestration | Needs a project brief; depends on P0 | Unscheduled | [#91](https://github.com/bluehexagons/infra_tools/issues/91) | Reuse setup parsing, workspace records, and transactional execution; do not create a second provisioning engine. |
| Agent VM workspaces and credentials | Proposed project brief; needs sequencing | Unscheduled | No dedicated issue | [Agent VM workspaces](AGENT_VM_WORKSPACES.md): make agent tools explicit, apply one Git credential/access policy per VM user, support active-user or specified-file credentials, and add guided interactive setup. |
| Recovery workflows | Queued behind transaction and deployment state | P2 | Recovery portion of [#97](https://github.com/bluehexagons/infra_tools/issues/97) | [Roadmap](ROADMAP.md), with Proxmox backup and restore details in the [Proxmox audit](PROXMOX_MAINTENANCE_AUDIT_2026-08-09.md). |
| Safe network apply and rollback | Address handoff delivered; firewall apply remains | P2 | No dedicated open issue | [Roadmap](ROADMAP.md): extend the verified host/guest address handoff model to reviewed Proxmox firewall artifacts with timed rollback and connectivity confirmation. |
| Extensibility and release quality | Queued | P3 | No dedicated open issue | [Roadmap](ROADMAP.md): plugin isolation, packaging smoke tests, lint/type/coverage gates, and a documented provider contract. |

## Unscheduled issue backlog

These open issues have a documented disposition but no standalone delivery
plan. Write or assign a project brief before implementation so they do not
silently compete with P0/P1 work.

| Issue | Disposition | Planning boundary |
| --- | --- | --- |
| [#85 — Improve RAM over-provisioning behavior](https://github.com/bluehexagons/infra_tools/issues/85) | Backlog | Define an explicit saved cluster/workload policy; do not infer cache pressure from VM labels. |
| [#28 — Scheduling system](https://github.com/bluehexagons/infra_tools/issues/28) | Backlog | Extend the storage orchestrator with maintenance windows, coordination, and resource-aware ordering. |
| [#83 — Apt cache support](https://github.com/bluehexagons/infra_tools/issues/83) | Backlog | Specify server ownership, validated client configuration, failure behavior, and rollback first. |
| [#87 — More default config options](https://github.com/bluehexagons/infra_tools/issues/87) | Backlog | Add a versioned preferences contract only when a supported desktop profile can own it. |
| [#25 — Multimedia packages](https://github.com/bluehexagons/infra_tools/issues/25) | Deferred | Reconsider after the transactional, audit, and recovery priorities are substantially complete. |

The five issues that appear complete in `main` are kept out of the project
queue and listed as closure candidates in the
[issue triage](GITHUB_ISSUE_TRIAGE_2026-08-17.md).

## Audit and decision records

| Document | Lifecycle | Use |
| --- | --- | --- |
| [Architectural risk review](ARCHITECTURAL_RISK_REVIEW_2026-08-07.md) | Reference with open findings | Evidence feeding transactional execution, startup isolation, and CI/CD trust-boundary work. |
| [Proxmox setup and maintenance audit](PROXMOX_MAINTENANCE_AUDIT_2026-08-09.md) | Active roadmap input | Proxmox update, observability, recovery, hardening, and policy slices. |
| [CLI-only agent host audit](AGENT_CLI_MAINTENANCE_AUDIT_2026-08-09.md) | Active roadmap input | Agent update lifecycle, maintenance windows, audit output, and cache/credential lifecycle. |
| [RDP desktop agent audit](DESKTOP_AGENT_MAINTENANCE_AUDIT_2026-08-09.md) | Active roadmap input | XRDP identity, configuration rollback, workload safety, and live smoke coverage. |
| [Test slop audit](TEST_SLOP_AUDIT_2026-08-09.md) | Complete reference | Records test-retention decisions; it is not active project work. |

## Keeping the portfolio current

When work lands, update the detailed owner first, then this index, the roadmap,
and the issue triage when their status or ordering changes. Do not create a new
plan for a slice already owned by one of the projects above. Move completed
audit documents to reference status rather than leaving them in the active
queue, and record newly deferred work explicitly instead of relying on file
age or issue inactivity.
