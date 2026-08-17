"""Controller-side verification for safe live network address transitions."""

from __future__ import annotations

import ipaddress
import subprocess
import time
from typing import Optional

from lib.config import SetupConfig
from lib.proxmox_network_transition import (
    ProxmoxNetworkPlan,
    apply_proxmox_network_plan,
    prepare_proxmox_network_plan,
    rollback_proxmox_network_plan,
)
from lib.ssh_utils import build_ssh_command, chain_remote_commands


REMOTE_INSTALL_DIR = "/opt/infra_tools"
PENDING_TRANSITION_PATH = "/run/infra-tools-network-transition.json"
VERIFY_ATTEMPTS = 12
VERIFY_INTERVAL_SECONDS = 2.0


def network_transition_targets(config: SetupConfig) -> list[str]:
    """Return normalized requested addresses in preferred SSH handoff order."""

    targets: list[str] = []
    for value in (config.static_ipv4, config.static_ipv6):
        if value:
            targets.append(str(ipaddress.ip_interface(value).ip))
    return targets


def _run_transition_ssh(
    config: SetupConfig,
    host: str,
    remote_command: str,
) -> subprocess.CompletedProcess[str]:
    command = build_ssh_command(
        host,
        "root",
        config.ssh_key,
        remote_command=remote_command,
        batch_mode=True,
        connect_timeout=5,
        server_alive_interval=5,
    )
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 255, "", str(exc))


def _wait_for_transition_ssh(
    config: SetupConfig,
    host: str,
    remote_command: str,
    *,
    attempts: int = VERIFY_ATTEMPTS,
    interval: float = VERIFY_INTERVAL_SECONDS,
) -> subprocess.CompletedProcess[str]:
    last_result: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in range(attempts):
        last_result = _run_transition_ssh(config, host, remote_command)
        if last_result.returncode == 0:
            return last_result
        if attempt + 1 < attempts:
            time.sleep(interval)
    assert last_result is not None
    return last_result


def _abort_transition(config: SetupConfig) -> None:
    abort_command = chain_remote_commands(
        [
            ["cd", REMOTE_INSTALL_DIR],
            ["python3", "-m", "common.network_steps", "--abort-transition"],
        ]
    )
    result = _run_transition_ssh(config, config.host, abort_command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "SSH unavailable").strip()
        print(f"  ⚠ Could not clean up the temporary network transition: {detail}")


def finish_network_transition(config: SetupConfig, setup_returncode: int) -> int:
    """Verify requested SSH addresses and commit or abort pending persistence."""

    if not config.activate_network or config.dry_run:
        return setup_returncode

    if setup_returncode != 0:
        _abort_transition(config)
        return setup_returncode

    targets = network_transition_targets(config)
    if not targets:
        print("  ✗ Network activation requested without a target address")
        _abort_transition(config)
        return 1

    pending_probe = f"test -f {PENDING_TRANSITION_PATH}"
    print("\nVerifying SSH access on the requested network address(es)...")
    for target in targets:
        result = _wait_for_transition_ssh(config, target, pending_probe)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "SSH unavailable").strip()
            print(f"  ✗ SSH verification failed for {target}: {detail}")
            _abort_transition(config)
            return 1
        print(f"  ✓ SSH reachable at {target}")

    proxmox_plan: Optional[ProxmoxNetworkPlan] = None
    try:
        proxmox_plan = prepare_proxmox_network_plan(config, config.host)
    except RuntimeError as exc:
        print(f"  ✗ Proxmox guest network preflight failed: {exc}")
        _abort_transition(config)
        return 1

    commit_command = chain_remote_commands(
        [
            ["cd", REMOTE_INSTALL_DIR],
            ["python3", "-m", "common.network_steps", "--commit-transition"],
        ]
    )
    commit_result = _run_transition_ssh(config, targets[0], commit_command)
    if commit_result.returncode != 0:
        detail = (commit_result.stderr or commit_result.stdout or "unknown error").strip()
        print(f"  ✗ New address is reachable, but persistence failed: {detail}")
        return 1

    for target in targets:
        result = _wait_for_transition_ssh(config, target, "true")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "SSH unavailable").strip()
            print(f"  ✗ SSH became unavailable at {target} after persistence: {detail}")
            return 1

    try:
        apply_proxmox_network_plan(proxmox_plan)
    except RuntimeError as exc:
        print(f"  ✗ Guest persistence succeeded, but Proxmox metadata failed: {exc}")
        return 1

    if (
        proxmox_plan is not None
        and proxmox_plan.requested_value != proxmox_plan.previous_value
    ):
        for target in targets:
            result = _wait_for_transition_ssh(config, target, "true")
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "SSH unavailable").strip()
                print(
                    f"  ✗ SSH became unavailable at {target} after the Proxmox "
                    f"metadata update: {detail}"
                )
                rollback_proxmox_network_plan(proxmox_plan)
                return 1

    previous_host = config.host
    config.host = targets[0]
    if previous_host == config.host:
        print(f"  ✓ Network activation verified at {config.host}")
    else:
        print(
            f"  ✓ Network handoff complete: {previous_host} → {config.host}; "
            "the previous live address remains until reboot"
        )
    return 0
