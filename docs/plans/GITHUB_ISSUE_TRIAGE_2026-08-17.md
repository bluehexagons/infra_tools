# GitHub Issue Triage (2026-08-17)

Status: current issue-to-implementation map. This repository-only update records
what the open issue text means against the current code and which project plan
owns the remaining work. It is not a substitute for the issue discussion or
acceptance criteria; GitHub issue state was not changed by this update.

## Triage rules

- Close an issue only when the requested operator-facing behavior is present,
  documented, and covered by focused tests where the repository can provide
  them.
- Keep an issue open when only a slice is implemented, when live-system
  validation is still required, or when the request needs a design decision.
- Treat this document and the linked roadmap plans as the implementation
  reference. Apply the corresponding state/comment changes on GitHub when the
  issue service is available.

## Complete in current main

| Issue | Result | Evidence |
| --- | --- | --- |
| [#79](https://github.com/bluehexagons/infra_tools/issues/79) | Complete; candidate for closure | `bootstrap`/`self-setup` installs the launcher, packages, and completions; `install.sh --local-setup` supports one-command local setup. See [Installation](../INSTALLATION.md). |
| [#81](https://github.com/bluehexagons/infra_tools/issues/81) | Complete for the requested lifecycle surface; candidate for closure | `infra-tools proxmox` supports live guest listing, status, start, stop, pause, resume, destroy, resource changes, disk resize, snapshots, health checks, and host registration in the workspace. Explicit desired-state guest inventory remains a separate follow-up under #91/#97. See [Proxmox workflows](../PROXMOX.md). |
| [#90](https://github.com/bluehexagons/infra_tools/issues/90) | Complete for Debian package-managed kernels; candidate for closure | `cleanup-maintenance` runs `apt-get autoremove --purge`, allowing APT's kernel-retention policy to remove superseded packages. Proxmox boot entries are intentionally outside this cleanup boundary. See [Recurring Maintenance](../MAINTENANCE.md). |
| [#92](https://github.com/bluehexagons/infra_tools/issues/92) | Complete; candidate for closure | Hosted setup defaults to VMs and provisions them with `qm` and cloud-init; guest management handles both `qm` VMs and `pct` containers. See [Proxmox workflows](../PROXMOX.md). |
| [#93](https://github.com/bluehexagons/infra_tools/issues/93) | Fixed; candidate for closure | `server_proxmox` defaults to no automatic restart and no forced restart deadline. Operators must opt in, and the behavior is documented in [Proxmox workflows](../PROXMOX.md). |

## Open, partially implemented

| Issue | Current slice | Remaining work and owner |
| --- | --- | --- |
| [#97](https://github.com/bluehexagons/infra_tools/issues/97) | Saved setup state is atomic, Proxmox hosts are workspace-registered, VM/LXC provisioning and lifecycle management exist, and read-only Proxmox planning/audit commands are available. | This remains the umbrella issue for the unfinished architecture: transactional setup/deploy activation, strict corrupt-state handling, verified SSH enrollment, and manifest-driven recovery. The owning plan is [Transactional execution](TRANSACTIONAL_EXECUTION.md) and the [roadmap](ROADMAP.md). |
| [#91](https://github.com/bluehexagons/infra_tools/issues/91) | An interactive Proxmox shell can select registered hosts, inspect guests, run lifecycle operations, and perform backups, migration, snapshots, and maintenance actions. | It does not yet create a new setup from an interactive form, queue/run arbitrary setup jobs, or monitor those jobs. Design it around the existing setup command, workspace records, and transactional execution rather than a second provisioning engine. |
| [#85](https://github.com/bluehexagons/infra_tools/issues/85) | Hosted VMs support an explicit `--balloon-min` lower bound; the default equals requested memory, so provisioning does not silently overcommit. Placement planning reports live memory headroom. | No automatic host page-cache policy is applied when memory is over-provisioned, and there is no saved cluster-wide overcommit policy. Any future policy must be explicit and workload-aware; do not infer safe cache pressure from a VM label. |
| [#63](https://github.com/bluehexagons/infra_tools/issues/63) | Workspace credentials support validated, mode-`0600` named credentials for Samba, SMB mounts, and Antistatic administration, with interactive set/list/remove commands. | Generic deployment secret references, optional secret-gated manifest components, rotation, and consumer inventory remain unimplemented. Continue with [Deploy secrets](DEPLOY_SECRETS.md). |
| [#58](https://github.com/bluehexagons/infra_tools/issues/58) | Shared notification targets are used by maintenance, security monitoring, storage operations, CI/CD, and ecosystem update jobs. The security monitor and storage runner collect and report several failure classes. | There is no unified diagnostics/audit contract covering shares, websites, repositories, timers, and repair actions. Extend the roadmap's read-only audit surface instead of adding another notification-only service. |
| [#38](https://github.com/bluehexagons/infra_tools/issues/38) | XRDP now uses the Xorg/xrdpdev path with dynamic-channel support, reconnectable native session policy, explicit channel controls, and documented troubleshooting. | The repository still lacks the disposable live VM/LXC smoke test for resize, disconnect/reconnect, and package-upgrade behavior. Keep this open until live evidence confirms the supported matrix. See [XRDP](../XRDP.md) and the [desktop audit](DESKTOP_AGENT_MAINTENANCE_AUDIT_2026-08-09.md). |
| [#28](https://github.com/bluehexagons/infra_tools/issues/28) | Sync and scrub specifications use a shared hourly timer, per-spec due intervals, atomic scheduling state, and a persistent lock to prevent overlap. | Cross-host coordination, configurable maintenance windows, and resource-aware ordering are not implemented. The next design should extend the existing storage orchestrator rather than add competing timers. See [Storage operations](../STORAGE_OPERATIONS.md). |

## Open, not implemented or deliberately deferred

| Issue | Decision |
| --- | --- |
| [#83](https://github.com/bluehexagons/infra_tools/issues/83) | No APT cache server installation or client proxy configuration exists. Plan the server package/service boundary, validated cache endpoint, client source configuration, and rollback behavior before implementation. |
| [#87](https://github.com/bluehexagons/infra_tools/issues/87) | The current profile defaults cover install-time choices such as browsers, office, RDP, agents, and maintenance policy. Panel layout and widget preferences are not modeled. Add a versioned desktop-preferences contract only if a supported desktop profile can own it. |
| [#25](https://github.com/bluehexagons/infra_tools/issues/25) | Multimedia flags and package bundles are not implemented. This remains deliberately deferred while the roadmap prioritizes transactional safety, audit/drift detection, and recovery over additional desktop applications. |

## Follow-up policy

New implementation work should update the owning roadmap plan and this issue
map in the same change. A closed issue should be reopened only for a concrete
regression or an acceptance criterion that was explicitly excluded from the
closure comment.
