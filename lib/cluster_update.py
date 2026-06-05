"""Rolling update helpers for ordered multi-node maintenance."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from lib.cache import load_setup_command
from lib.config import SetupConfig
from lib.setup_common import prepare_validated_runtime_config
from lib.ssh_utils import build_ssh_command
from lib.workspace import set_workspace_dir


_LOCALHOSTS = {"localhost", "127.0.0.1", "::1"}
_SSH_POLL_INTERVAL = 5
_REBOOT_SHUTDOWN_TIMEOUT = 90


@dataclass
class ClusterUpdateResult:
    target: str
    host: Optional[str]
    status: str
    details: str = ""
    reboot_required: bool = False
    rebooted: bool = False


def _ssh_result(
    config: SetupConfig,
    remote_command: str,
    *,
    connect_timeout: int = 5,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        build_ssh_command(
            config.host,
            "root",
            config.ssh_key,
            remote_command=remote_command,
            batch_mode=True,
            connect_timeout=connect_timeout,
            server_alive_interval=connect_timeout,
        ),
        capture_output=True,
        text=True,
        check=False,
    )


def _ssh_available(config: SetupConfig) -> bool:
    return _ssh_result(config, "true").returncode == 0


def _wait_for_ssh_state(
    config: SetupConfig,
    *,
    available: bool,
    timeout: int,
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ssh_available(config) == available:
            return True
        time.sleep(_SSH_POLL_INTERVAL)
    return _ssh_available(config) == available


def _remote_reboot_required(config: SetupConfig) -> bool:
    return _ssh_result(config, "test -f /var/run/reboot-required").returncode == 0


def _reboot_and_wait(config: SetupConfig, timeout: int) -> None:
    reboot_command = (
        "nohup sh -lc "
        "'sleep 1 && shutdown -r now \"infra_tools rolling update\"' "
        ">/dev/null 2>&1 </dev/null &"
    )
    _ssh_result(config, reboot_command, connect_timeout=15)

    shutdown_timeout = min(
        _REBOOT_SHUTDOWN_TIMEOUT,
        max(1, timeout // 3),
    )
    if not _wait_for_ssh_state(config, available=False, timeout=shutdown_timeout):
        raise RuntimeError(
            f"{config.host} never went offline after the reboot request"
        )

    startup_timeout = max(1, timeout - shutdown_timeout)
    if not _wait_for_ssh_state(config, available=True, timeout=startup_timeout):
        raise RuntimeError(f"{config.host} did not return over SSH after reboot")


def _print_summary(results: list[ClusterUpdateResult]) -> None:
    print()
    print("=" * 60)
    print("Rolling update summary")
    print("=" * 60)
    for result in results:
        extras: list[str] = []
        if result.reboot_required:
            extras.append("reboot-required")
        if result.rebooted:
            extras.append("rebooted")
        suffix = f" ({', '.join(extras)})" if extras else ""
        detail = f" - {result.details}" if result.details else ""
        host = result.host or "-"
        print(f"{result.status.upper():<9} {result.target} [{host}]{suffix}{detail}")
    print("=" * 60)


def run_cluster_update(
    targets: list[str],
    *,
    workspace: Optional[str] = None,
    dry_run: bool = False,
    reboot_timeout: int = 300,
) -> int:
    if workspace:
        set_workspace_dir(workspace)
    if reboot_timeout <= 0:
        raise ValueError("--reboot-timeout must be positive")

    prepared: list[tuple[str, SetupConfig]] = []
    results: list[ClusterUpdateResult] = []

    for target in targets:
        config = load_setup_command(target)
        if config is None:
            results.append(
                ClusterUpdateResult(
                    target=target,
                    host=None,
                    status="failed",
                    details="No saved setup command found",
                )
            )
            continue
        if config.host in _LOCALHOSTS:
            results.append(
                ClusterUpdateResult(
                    target=target,
                    host=config.host,
                    status="failed",
                    details="Localhost targets are not supported for rolling updates",
                )
            )
            continue

        config.dry_run = dry_run
        try:
            prepare_validated_runtime_config(config, workspace)
        except ValueError as exc:
            results.append(
                ClusterUpdateResult(
                    target=target,
                    host=config.host,
                    status="failed",
                    details=str(exc),
                )
            )
            continue
        prepared.append((target, config))

    if len(prepared) != len(targets):
        print("Preflight failed; no systems were changed.")
        _print_summary(results)
        return 1

    from infra_tools import _execute_patch_config

    for index, (target, config) in enumerate(prepared):
        result = ClusterUpdateResult(
            target=target,
            host=config.host,
            status="failed",
        )
        results.append(result)

        if _execute_patch_config(config) != 0:
            result.details = "Patch run failed"
            for skipped_target, skipped_config in prepared[index + 1 :]:
                results.append(
                    ClusterUpdateResult(
                        target=skipped_target,
                        host=skipped_config.host,
                        status="skipped",
                        details=f"Skipped after failure on {target}",
                    )
                )
            _print_summary(results)
            return 1

        result.status = "updated"
        if dry_run:
            result.details = "Dry run only"
            continue

        reboot_required = _remote_reboot_required(config)
        result.reboot_required = reboot_required
        if not reboot_required:
            result.details = "No reboot required"
            continue

        try:
            _reboot_and_wait(config, reboot_timeout)
        except RuntimeError as exc:
            result.status = "failed"
            result.details = str(exc)
            for skipped_target, skipped_config in prepared[index + 1 :]:
                results.append(
                    ClusterUpdateResult(
                        target=skipped_target,
                        host=skipped_config.host,
                        status="skipped",
                        details=f"Skipped after failure on {target}",
                    )
                )
            _print_summary(results)
            return 1

        result.rebooted = True
        result.details = "Rebooted and reconnected"

    _print_summary(results)
    return 0


__all__ = ["ClusterUpdateResult", "run_cluster_update"]
