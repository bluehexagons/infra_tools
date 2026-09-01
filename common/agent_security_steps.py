"""System policy for safer Codex sessions on coding-agent machines."""

from __future__ import annotations

import os
import stat
import tomllib

from lib.atomic_io import write_text_atomic
from lib.config import SetupConfig
from lib.remote_utils import is_dry_run


CODEX_SYSTEM_CONFIG_DIR = "/etc/codex"
CODEX_SYSTEM_CONFIG_NAME = "config.toml"
CODEX_REQUIREMENTS_NAME = "requirements.toml"
_MANAGED_MARKER = "# Managed by infra-tools coding-agent security policy."


def _codex_config_content(*, hardened: bool) -> str:
    approval_policy = "never" if hardened else "on-request"
    reviewer = "user" if hardened else "auto_review"
    hardening = "allow_login_shell = false\n" if hardened else ""
    return (
        f"{_MANAGED_MARKER}\n"
        f"# Policy: {'hardened' if hardened else 'standard'}\n"
        f'approval_policy = "{approval_policy}"\n'
        f'approvals_reviewer = "{reviewer}"\n'
        'sandbox_mode = "workspace-write"\n'
        'default_permissions = ":workspace"\n'
        f"{hardening}"
        "\n[sandbox_workspace_write]\n"
        "network_access = false\n"
    )


def _codex_requirements_content(*, hardened: bool) -> str:
    approval_policy = "never" if hardened else "on-request"
    reviewer = "user" if hardened else "auto_review"
    hardening = (
        "allow_login_shell = false\n"
        "allow_managed_hooks_only = true\n"
        "allow_browser_and_computer_use = false\n"
        "allow_appshots = false\n"
        "allow_remote_control = false\n"
        if hardened
        else ""
    )
    return (
        f"{_MANAGED_MARKER}\n"
        f"# Policy: {'hardened' if hardened else 'standard'}\n"
        f'allowed_approval_policies = ["{approval_policy}"]\n'
        f'allowed_approvals_reviewers = ["{reviewer}"]\n'
        'allowed_sandbox_modes = ["read-only", "workspace-write"]\n'
        'default_permissions = ":workspace"\n'
        f"{hardening}"
        "\n[allowed_permission_profiles]\n"
        '":read-only" = true\n'
        '":workspace" = true\n'
    )


def _ensure_codex_policy_directory() -> None:
    if os.path.lexists(CODEX_SYSTEM_CONFIG_DIR):
        directory_stat = os.lstat(CODEX_SYSTEM_CONFIG_DIR)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise RuntimeError(
                f"Refusing unsafe Codex policy directory: {CODEX_SYSTEM_CONFIG_DIR}"
            )
        return
    os.makedirs(CODEX_SYSTEM_CONFIG_DIR, mode=0o755)


def _validate_managed_codex_policy_target(path: str) -> None:
    """Reject unsafe or administrator-owned policy paths before any write."""

    if os.path.lexists(path):
        path_stat = os.lstat(path)
        if not stat.S_ISREG(path_stat.st_mode):
            raise RuntimeError(f"Refusing unsafe Codex policy path: {path}")
        with open(path, "r", encoding="utf-8") as file_obj:
            existing = file_obj.read()
        if not existing.startswith(f"{_MANAGED_MARKER}\n"):
            raise RuntimeError(
                f"Refusing to replace unmanaged Codex policy: {path}"
            )


def _write_managed_codex_policy(path: str, content: str) -> None:
    """Atomically replace only an absent or infra-tools-owned policy file."""

    tomllib.loads(content)
    _validate_managed_codex_policy_target(path)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file_obj:
            existing = file_obj.read()
        if existing == content:
            os.chown(path, 0, 0)
            os.chmod(path, 0o644)
            return

    write_text_atomic(path, content, mode=0o644)
    os.chown(path, 0, 0)
    os.chmod(path, 0o644)


def configure_codex_security_policy(config: SetupConfig) -> None:
    """Set and enforce the selected Codex approval and workspace boundary."""

    policy_name = "hardened" if config.harden_agent else "auto-reviewed workspace"
    if is_dry_run():
        print(f"  [DRY-RUN] Would configure the Codex {policy_name} policy")
        return

    _ensure_codex_policy_directory()
    config_path = os.path.join(
        CODEX_SYSTEM_CONFIG_DIR, CODEX_SYSTEM_CONFIG_NAME
    )
    requirements_path = os.path.join(
        CODEX_SYSTEM_CONFIG_DIR, CODEX_REQUIREMENTS_NAME
    )
    config_content = _codex_config_content(hardened=config.harden_agent)
    requirements_content = _codex_requirements_content(
        hardened=config.harden_agent
    )
    tomllib.loads(config_content)
    tomllib.loads(requirements_content)
    _validate_managed_codex_policy_target(config_path)
    _validate_managed_codex_policy_target(requirements_path)
    _write_managed_codex_policy(
        config_path,
        config_content,
    )
    _write_managed_codex_policy(
        requirements_path,
        requirements_content,
    )
    print(f"  ✓ Codex {policy_name} policy configured")
