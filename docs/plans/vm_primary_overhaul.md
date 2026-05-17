# VM-First Overhaul Plan

This plan covers the shift from an LXC-first mindset to treating VMs as the primary supported guest type for `infra_tools`, with LXC retained as a lighter-weight compatibility path.

Today, the codebase already has solid VM building blocks (`lib/proxmox_vm.py`, machine capability helpers, and VM documentation), but the overall product posture is still container-first in defaults, examples, and several edge-case workarounds. The goal of this overhaul is to make desktop, web, and build-server workflows feel native on VMs without trying to preserve feature parity for every LXC-specific desktop quirk.

## Current State

- `DEFAULT_MACHINE_TYPE` is still `unprivileged`, so the fallback posture is LXC-centric even though VM and hardware share the more complete capability set.
- Hosted setup documentation still leads with LXC examples, with VM shown as an alternate path afterward.
- Hosted argument help and command docs still describe the Proxmox flow primarily as container creation.
- Runtime capability checks already distinguish "full system control" environments (`vm`, `privileged`, `hardware`) from containerized ones, so much of the code is structurally ready for a VM-first policy.
- Security, time sync, swap, and some desktop/RDP logic still carry container-specific fallbacks and warnings that reflect the older default deployment target.

## Goals

1. Make VMs the default and recommended guest type for hosted desktop, web, and build-server setups.
2. Keep LXC working for basic server and lightweight utility cases, but stop optimizing around every LXC-only desktop edge case.
3. Improve VM provisioning so first boot, remote access, guest lifecycle, and post-provision setup feel smoother than the LXC path.
4. Reframe docs, examples, and tests around VM-first expectations.

## Non-Goals

- Perfect behavioral parity between LXC and VMs.
- Preserving every LXC desktop workaround if it adds complexity without helping the VM-first path.
- Removing LXC support entirely.

## Recommended Workstreams

### 1. Flip the product posture to VM-first

Change the visible defaults so the common path points at VMs instead of unprivileged containers.

- Set VM defaults for the system types that are expected to become VM-backed most often:
  - `workstation_desktop`
  - `workstation_dev`
  - `pc_dev`
  - `server_web`
  - build-server flows when `--build-server` is enabled
- Reword CLI help and docs so `--machine vm` is presented as the normal hosted Proxmox path, while `--machine unprivileged` is the explicit "lightweight LXC" choice.
- Consider replacing the single global fallback of `unprivileged` with either:
  - system-type defaults that prefer `vm` where appropriate, or
  - an `auto`/resolved default model that prefers `vm` for hosted guests and preserves `hardware` for direct host setup.

**Recommendation:** Prefer per-system-type defaults first. It is smaller than introducing a new machine type and aligns with the existing plugin metadata model.

### 2. Make Proxmox VM provisioning more seamless than LXC

The VM path should feel complete enough that there is no reason to fall back to LXC for common desktop or web setups.

- Expand `lib/proxmox_vm.py` to treat the VM baseline as a first-class product surface:
  - ensure `qemu-guest-agent` is installed and started early
  - wait on guest-agent/network readiness when available, not just SSH reachability
  - expose sensible VM defaults for ballooning, RNG, CPU type, and guest agent
  - keep console access predictable (serial console already exists; keep it standardized in docs and health checks)
  - make image caching and reuse explicit so repeated VM creation is fast and unsurprising
- Improve first-boot cloud-init so the created VM is immediately ready for the normal remote setup phase with minimal manual recovery scenarios.
- Add stronger validation around VM storage expectations so LVM-backed root storage, cloud-init drive placement, and image source selection fail fast with clear guidance.

**Recommendation:** Make the VM path the most reliable hosted path, not just the most capable one.

### 3. Reduce container-specific branching to a compatibility layer

A lot of the current branching is already capability-based, which is good. The next step is to stop letting container limitations dominate the default control flow.

- Keep using capability helpers (`can_modify_kernel()`, `can_manage_firewall()`, `has_gpu_access()`, etc.), but audit them with a VM-first lens.
- Move LXC-only warnings, fallbacks, and desktop compatibility tweaks behind narrower checks instead of treating them as the baseline behavior.
- Where code currently handles "container vs everything else", make sure the mainline path is optimized for `vm`/`hardware`, with LXC following a reduced-support branch.
- Keep skip behavior explicit for unsupported LXC features (sysctl, fail2ban, swap, time sync), but avoid adding new feature work that only exists to smooth over LXC limitations.

**Recommendation:** Preserve the capability model, but treat LXC as a constrained fallback rather than the reference environment.

### 4. Split desktop/RDP behavior into VM-first and container-compat modes

Desktop polish is one of the clearest places where VM-first support should pay off.

- Separate XRDP/Xorg tuning for VMs from the container-safe fallback profile.
- Revisit settings that were chosen mainly to keep unprivileged containers stable, especially around acceleration and resize behavior.
- Favor the VM path for:
  - GPU/render group access
  - smoother XRDP startup
  - fewer forced software-rendering assumptions
  - better default desktop behavior under reconnects and resize events
- Keep LXC desktop support basic:
  - session starts
  - keyboard/mouse work
  - standard resolutions work
  - advanced dynamic resize or GPU-related polish is not a blocker

**Recommendation:** Make VM desktop behavior excellent and accept "good enough" LXC desktop behavior.

### 5. Align server and build-server expectations with VM capabilities

Web and build-server roles benefit directly from moving away from container constraints.

- Treat VMs as the standard target for:
  - UFW-managed firewalls
  - fail2ban
  - kernel hardening
  - swap
  - chrony/time sync
  - CI/build workloads with more predictable isolation and reboot behavior
- Review build-server docs and examples so the standard deployment story assumes a VM host, not an LXC unless the user explicitly wants the trade-off.
- Keep LXC as an option for small, disposable, or intentionally constrained services.

**Recommendation:** For any workflow that depends on full service management or long-lived CI/build workloads, optimize for VMs first.

### 6. Rebuild docs and examples around the new default

The docs should stop teaching LXC as the primary hosted path.

- Update README examples so VM workflows appear first and LXC is the alternate/minimal path.
- Update `docs/MACHINE_TYPES.md` so VM is described as the preferred hosted guest for most real setups.
- Rename or rewrite command-reference sections that currently say "Hosted Proxmox LXC" when the flags now drive either VMs or containers.
- Add a concise decision guide:
  - use **VM** for desktops, web servers, build servers, GPU/DRI, kernel tuning, firewalling, and anything needing normal system semantics
  - use **LXC** for lightweight services, quick test guests, or intentionally constrained environments

**Recommendation:** Every top-level example should make the VM path easy to copy without reading the LXC caveats first.

### 7. Rebalance testing around VM confidence

The test mix should reflect the new support priority.

- Add or expand unit coverage for VM-default resolution and validation.
- Keep live Proxmox coverage for both guest types, but shift the main confidence path toward VMs:
  - VM provisioning smoke test
  - VM setup handoff smoke test
  - VM-specific regression coverage for guest-agent/cloud-init readiness
- Retain a smaller LXC compatibility suite that proves:
  - provisioning still works
  - basic remote setup still works
  - known unsupported features fail or skip cleanly
- Make new desktop/RDP regressions block VM flows first; LXC desktop regressions are lower severity unless they break basic access.

**Recommendation:** Test LXC for survivability, and test VMs for polish.

## Suggested Implementation Order

### Phase 1: Defaults and messaging

- Add VM defaults in plugin metadata and any hosted-setup resolution paths.
- Rewrite docs/help/examples to lead with VM workflows.
- Keep LXC explicitly available with `--machine unprivileged`.

### Phase 2: VM provisioning baseline

- Strengthen `lib/proxmox_vm.py` readiness, validation, and guest-agent expectations.
- Standardize the baseline VM features and document them.

### Phase 3: Capability and step cleanup

- Audit security/common/desktop steps for container-first assumptions.
- Remove or narrow LXC-specific compatibility code that no longer justifies its maintenance cost.

### Phase 4: VM desktop and build-server polish

- Split VM vs LXC XRDP behavior where needed.
- Review build-server defaults and docs with VM-first assumptions.

### Phase 5: Test matrix rebalance

- Expand VM coverage.
- Keep a smaller, explicit LXC compatibility lane.

## Likely Code and Doc Surfaces

- `lib/config.py`
- `lib/arg_parser.py`
- `lib/setup_common.py`
- `lib/machine_state.py`
- `lib/proxmox_vm.py`
- `lib/proxmox_node.py`
- `plugins/server.py`
- `plugins/workstation.py`
- `desktop/xrdp_steps.py`
- `desktop/desktop_environment_steps.py`
- `common/common_steps.py`
- `security/security_steps.py`
- `README.md`
- `docs/MACHINE_TYPES.md`
- `docs/COMMAND_LINE.md`
- `tests/test_machine_state.py`
- `tests/test_proxmox_vm.py`
- XRDP/security/setup regression tests touching container-vs-VM behavior

## Acceptance Criteria

- Hosted workstation, web, and build-server documentation leads with VM examples.
- Common hosted flows choose VM defaults without requiring users to discover `--machine vm`.
- VM provisioning reaches a reliably usable SSH-ready guest with guest-agent-aware lifecycle expectations.
- Security and service-management features work out of the box on the default VM path.
- LXC still provisions and runs basic setup flows, but advanced desktop parity is no longer required.
- The automated test mix clearly prioritizes VM behavior while preserving a minimal LXC compatibility signal.

## Bottom-Line Recommendation

Do not try to make LXC and VMs equally polished. Make VMs the default, easiest, and most fully supported path for desktops, web workloads, and build servers; keep LXC available as a simpler compatibility target with clearly reduced expectations.
