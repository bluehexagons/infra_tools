# Future Ideas and Enhancements

This file captures potential improvements and follow-up work for infra_tools.

## Completed in Major Revision Branch

- **#79 Self-setup**: Launcher install for `infra_tools` command on PATH, system-wide and per-user
- **#27 Interactive CLI**: Top-level `shell` subcommand with REPL for configuration management
- **#82 Proxmox Notifications**: Native Proxmox webhook notifications via `pvesh`
- **#84 Live LXC Integration Test**: `test_proxmox_live.py` with `INFRA_TOOLS_RUN_LIVE_PROXMOX=1` gating
- **#89 Node version cleanup**: Stale nvm version removal in cleanup maintenance
- **#88 Bundler cleanup** (partial): Cleanup scanning `/var/tmp` for `bundler*` directories

## Open Issues

### #81: Container Lifecycle Modifications

The Proxmox container management system supports create/start/stop/destroy/health, but not yet:
- Modify container flags (CPU, RAM, disk)
- Reconfigure container networking
- Re-deploy on modified containers
- In-place updates without recreate

**Impact**: Users cannot adjust container resources after creation or redeploy changes without full destroy/recreate.

**Approach**:
- Add `lib/proxmox_manage.reconfigure_container(host, vmid, **flags)` wrapping `pct config` and `pct pending`
- Add `lib/proxmox_manage.modify_container(host, vmid, cpu, memory, disk)` for resource changes
- Extend CLI with `proxmox reconfigure <host> <vmid> ...` and `proxmox modify <host> <vmid> --cpu N --memory XG`
- Add interactive shell commands for these operations

### #27: Broader Interactive CLI Features (Partial)

The shell covers basic configuration management. Enhancements could include:
- **Shell history**: Persistent command history file (`~/.local/share/infra_tools/shell_history`)
- **Autocompletion within shell**: Tab-complete patterns, hosts, vmids, subcommands (requires upstream `readline` integration or custom solution)
- **Configuration templates**: `template list`, `template show`, save/load partial setups as templates
- **Batch operations**: `deploy prod web* --yes` to deploy multiple matched configurations at once
- **Init file support**: `~/.infra_toolsrc` for shell startup commands/aliases
- **Workspace shortcuts**: Quick aliases within shell to switch between workspaces (e.g., `ws prod`, `ws staging`)
- **Output formatting**: `list --json`, `info --compact`, etc. for scripting

### #88: Comprehensive /tmp Cleanup (Partial)

The current approach handles stale bundler directories in `/var/tmp`, but doesn't fully address:
- Transient build artifacts in `/tmp` from concurrent operations
- Systemd-tmpfiles policies for automatic aging
- tmpfs mount configuration to prevent filling /tmp
- Monitor and alert on /tmp usage

**Approach**:
- Add `/etc/tmpfiles.d/infra_tools.conf` to auto-age and remove aged artifacts
- Implement `--set-tmpfs-limit SIZE` option for bootstrap to configure `/tmp` tmpfs mount size
- Add periodic monitoring via cleanup maintenance to log /tmp usage trends
- Document best practices for tmpfs sizing on orchestration hosts

## Performance & Scalability

- **Configuration search**: `list` and `info` commands scan all saved configs; large workspaces (1000+) may be slow
  - Add indexing or caching layer for frequent patterns
  - Add filtering options (e.g., `list --tags prod --before 2025-01-01`)

- **Proxmox API overhead**: Commands that list/query containers make sequential SSH calls per host
  - Batch operations where possible
  - Async/parallel queries across multiple hosts

## Testing Infrastructure

- **Live Proxmox test**: Currently requires manual `PROXMOX_TEST_HOST` environment setup; could expand to:
  - Container creation/deletion lifecycle
  - Notification delivery verification
  - Multi-host coordination tests

- **CI/CD integration**: Add pre-merge checks for documentation, shell completions, help text consistency

## Documentation & UX

- **Interactive shell guide**: Dedicated tutorial (e.g., `docs/INTERACTIVE_SHELL.md`)
- **Quick-start with launcher**: Beginner-friendly setup guide for new users
- **Error recovery guide**: Common failures (network, SSH, disk space) and recovery steps
- **Workspace management guide**: Best practices for multi-environment setups

## Maintenance

- **Dependency updates**: `uv`, `argcomplete` pinning and update strategy
- **Python version support**: Currently requires 3.10+; could consider backport or security fixes for 3.9
- **Debian version support**: Test on current and LTS releases

## Known Limitations

- **SSH key management**: Currently supports per-host keys; no agent forwarding or multi-key support
- **Credential storage**: Workspace credentials stored in plaintext; consider encryption at rest
- **Network resilience**: SSH connection drops during long operations may leave partial state
- **Concurrency**: Multiple infra_tools processes operating on same workspace could race on saves
