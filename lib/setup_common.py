#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pwd
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Optional, Callable

try:
    import argcomplete
except ImportError:
    argcomplete = None

from lib.config import DEFAULT_MACHINE_TYPE, SetupConfig, _normalize_container_storage
from lib.credentials import prepare_runtime_config, store_cli_credentials
from lib.proxmox_hosts import ProxmoxHost, find_proxmox_host, sync_proxmox_host
from lib.validators import validate_host, validate_username
from lib.validation import (
    validate_apt_packages,
    validate_agent_repositories,
    validate_antistatic_settings,
    validate_deploy_specs,
    validate_deploy_targets,
    validate_gogs_settings,
    validate_hosted_flags,
    validate_rdp_settings,
    validate_samba_share_credentials,
    validate_samba_share_specs,
    validate_smb_mount_specs,
    validate_scrub_specs,
    validate_ssl_email,
    validate_sync_specs,
    validate_memory_string,
    validate_timezone_name,
    validate_workspace_dir,
)
from lib.system_utils import get_current_username
from lib.cache import save_setup_command
from lib.arg_parser import create_setup_argument_parser
from lib.display import print_setup_summary
from lib.notifications import validate_notification_args
from lib.ssh_utils import build_ssh_command, chain_remote_commands
from lib.workspace import set_workspace_dir
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "..", "remote_setup.py")
LIB_DIR = SCRIPT_DIR
CONFIG_DIR = os.path.join(SCRIPT_DIR, "..", "config")
SERVICE_TOOLS_DIR = os.path.join(SCRIPT_DIR, "..", "service_tools")
REMOTE_INSTALL_DIR = "/opt/infra_tools"
GIT_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/git_repos")
REMOTE_ARGS_FILENAME = ".remote_setup_args.json"
AGENT_REPOS_DIRNAME = "agent_repos"
AGENT_PAYLOAD_DIRNAME = "agent_payload"


def _repository_cache_path(cache_dir: str, git_url: str, repo_name: str) -> str:
    """Return a cache path unique to the complete repository URL."""
    url_digest = hashlib.sha256(git_url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(cache_dir, f"{repo_name}-{url_digest}")


def clone_repository(git_url: str, temp_dir: str, cache_dir: Optional[str] = None, dry_run: bool = False) -> Optional[tuple[str, Optional[str]]]:
    repo_name = git_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]

    if repo_name in {"", ".", ".."}:
        print(f"  Error: unsafe repository name derived from {git_url}")
        return None
    
    clone_path = os.path.join(temp_dir, repo_name)
    
    if cache_dir:
        cache_path = _repository_cache_path(cache_dir, git_url, repo_name)
        
        if os.path.exists(cache_path):
            print(f"  Updating cached repository {repo_name}...")
            if not dry_run:
                try:
                    result = subprocess.run(
                        ["git", "-C", cache_path, "fetch", "--all"],
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if result.returncode != 0:
                        print(f"  Error fetching updates: {result.stderr}")
                        return None
                    
                    result = subprocess.run(
                        ["git", "-C", cache_path, "symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.returncode == 0:
                        default_branch = result.stdout.strip()
                    else:
                        for branch in ["origin/main", "origin/master"]:
                            result = subprocess.run(
                                ["git", "-C", cache_path, "rev-parse", "--verify", branch],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )
                            if result.returncode == 0:
                                default_branch = branch
                                break
                        else:
                            print(f"  Error: Could not determine default branch")
                            return None
                    
                    result = subprocess.run(
                        ["git", "-C", cache_path, "reset", "--hard", default_branch],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.returncode != 0:
                        print(f"  Error resetting repository: {result.stderr}")
                        return None

                    result = subprocess.run(
                        ["git", "-C", cache_path, "clean", "-fdx"],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.returncode != 0:
                        print(f"  Error cleaning repository: {result.stderr}")
                        return None

                    print(f"  ✓ Updated cached repository")
                except Exception as e:
                    print(f"  Error updating repository: {e}")
                    return None
            else:
                print(f"  [DRY RUN] Would fetch and reset cached repository")
        else:
            print(f"  Caching {git_url}...")
            if not dry_run:
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                    result = subprocess.run(
                        ["git", "clone", git_url, cache_path],
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if result.returncode != 0:
                        print(f"  Error cloning repository: {result.stderr}")
                        return None
                    print(f"  ✓ Cached to {cache_path}")
                except Exception as e:
                    print(f"  Error caching repository: {e}")
                    return None
            else:
                print(f"  [DRY RUN] Would clone to cache")
        
        if not dry_run:
            try:
                if os.path.exists(clone_path):
                    shutil.rmtree(clone_path)
                shutil.copytree(cache_path, clone_path, symlinks=True)
                print(f"  ✓ Copied to {clone_path}")
            except Exception as e:
                print(f"  Error copying repository: {e}")
                return None
        else:
            print(f"  [DRY RUN] Would copy to {clone_path}")
        
        commit_hash = None
        if not dry_run:
            from lib.deploy_utils import get_git_commit_hash
            commit_hash = get_git_commit_hash(clone_path)
        
        return (clone_path, commit_hash)
    else:
        print(f"  Cloning {git_url}...")
        if dry_run:
            print(f"  [DRY RUN] Would clone to {clone_path}")
            return (clone_path, None)
        
        try:
            result = subprocess.run(
                ["git", "clone", git_url, clone_path],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode != 0:
                print(f"  Error cloning repository: {result.stderr}")
                return None
            print(f"  ✓ Cloned to {clone_path}")
            
            from lib.deploy_utils import get_git_commit_hash
            commit_hash = get_git_commit_hash(clone_path)
            
            return (clone_path, commit_hash)
        except Exception as e:
            print(f"  Error cloning repository: {e}")
            return None


def copy_project_files(dest_dir: str) -> None:
    project_root = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
    items_to_copy = [
        "infra_tools.py",
        "remote_setup.py",
        "lib",
        "plugins",
        "game",
        "desktop",
        "web",
        "smb",
        "security",
        "sync",
        "common",
        "deploy",
    ]
    
    for item in items_to_copy:
        src = os.path.join(project_root, item)
        dst = os.path.join(dest_dir, item)
        if os.path.exists(src):
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git'))
            else:
                shutil.copy2(src, dst)


def prepare_deployments(config: SetupConfig, target_dir: str) -> None:
    if not config.deploy_specs:
        return
        
    print(f"\n{'='*60}")
    print("Cloning repositories locally...")
    print(f"{'='*60}")
    
    for _deploy_spec, git_url in config.deploy_specs:
        result = clone_repository(git_url, target_dir, cache_dir=GIT_CACHE_DIR, dry_run=config.dry_run)
        if result is not None:
            clone_path, commit_hash = result
            if commit_hash and not config.dry_run:
                repo_name = os.path.basename(clone_path)
                commit_file = os.path.join(target_dir, f"{repo_name}.commit")
                with open(commit_file, 'w') as f:
                    f.write(commit_hash)
        else:
            print(f"Warning: Failed to clone {git_url}, skipping...")


def prepare_agent_repositories(config: SetupConfig, target_dir: str) -> None:
    if not config.agent_repos:
        return

    validate_agent_repositories(config.agent_repos)

    print(f"\n{'='*60}")
    print("Cloning agent repositories locally...")
    print(f"{'='*60}")

    for git_url in config.agent_repos:
        result = clone_repository(git_url, target_dir, cache_dir=GIT_CACHE_DIR, dry_run=config.dry_run)
        if result is None:
            raise RuntimeError(f"Failed to clone requested agent repository: {git_url}")


def _local_user_home() -> str:
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        try:
            return pwd.getpwnam(sudo_user).pw_dir
        except KeyError:
            pass
    return os.path.expanduser("~")


def _copy_existing_path(source: str, destination: str) -> bool:
    if not os.path.exists(source):
        return False

    os.makedirs(os.path.dirname(destination), exist_ok=True)
    if os.path.isdir(source):
        shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)
    return True


def _prepare_opencode_payload(config: SetupConfig, payload_dir: str, local_home: str) -> None:
    if config.copy_agent_config:
        source = os.path.join(local_home, ".config", "opencode")
        destination = os.path.join(payload_dir, "config", "opencode")
        if _copy_existing_path(source, destination):
            print("  Staged OpenCode config")
        else:
            print(f"  No OpenCode config found at {source}")

    if config.copy_agent_keys:
        source = os.path.join(local_home, ".local", "share", "opencode", "auth.json")
        destination = os.path.join(payload_dir, "secrets", "opencode", "auth.json")
        if _copy_existing_path(source, destination):
            os.chmod(destination, 0o600)
            print("  Staged OpenCode credentials")
        else:
            print(f"  No OpenCode credentials found at {source}")


def _stage_selected_agent_config(
    source_dir: str,
    destination_dir: str,
    names: tuple[str, ...],
) -> bool:
    staged = False
    for name in names:
        staged = _copy_existing_path(
            os.path.join(source_dir, name),
            os.path.join(destination_dir, name),
        ) or staged
    return staged


def _prepare_codex_payload(config: SetupConfig, payload_dir: str, local_home: str) -> None:
    codex_dir = os.path.join(local_home, ".codex")
    if config.copy_agent_config:
        destination = os.path.join(payload_dir, "config", "codex")
        staged = _stage_selected_agent_config(
            codex_dir,
            destination,
            ("config.toml", "AGENTS.md", "skills", "rules"),
        )
        print("  Staged Codex config" if staged else f"  No Codex config found at {codex_dir}")

    if config.copy_agent_keys:
        source = os.path.join(codex_dir, "auth.json")
        destination = os.path.join(payload_dir, "secrets", "codex", "auth.json")
        if _copy_existing_path(source, destination):
            os.chmod(destination, 0o600)
            print("  Staged Codex credentials")
        else:
            print(f"  No Codex credentials found at {source}")


def _prepare_claude_payload(config: SetupConfig, payload_dir: str, local_home: str) -> None:
    claude_dir = os.path.join(local_home, ".claude")
    if config.copy_agent_config:
        destination = os.path.join(payload_dir, "config", "claude")
        staged = _stage_selected_agent_config(
            claude_dir,
            destination,
            ("settings.json", "CLAUDE.md", "commands", "agents", "skills", "plugins"),
        )
        print(
            "  Staged Claude Code config"
            if staged
            else f"  No Claude Code config found at {claude_dir}"
        )

    if config.copy_agent_keys:
        source = os.path.join(claude_dir, ".credentials.json")
        destination = os.path.join(
            payload_dir,
            "secrets",
            "claude",
            ".credentials.json",
        )
        if _copy_existing_path(source, destination):
            os.chmod(destination, 0o600)
            print("  Staged Claude Code credentials")
        else:
            print(f"  No Claude Code credentials found at {source}")


def _prepare_github_cli_payload(config: SetupConfig, payload_dir: str, local_home: str) -> None:
    gh_config_dir = os.path.join(local_home, ".config", "gh")

    if config.copy_agent_config:
        staged = False
        for filename in ("config.yml", "aliases.yml"):
            source = os.path.join(gh_config_dir, filename)
            destination = os.path.join(payload_dir, "config", "gh", filename)
            staged = _copy_existing_path(source, destination) or staged

        extensions_source = os.path.join(gh_config_dir, "extensions")
        extensions_destination = os.path.join(payload_dir, "config", "gh", "extensions")
        staged = _copy_existing_path(extensions_source, extensions_destination) or staged

        if staged:
            print("  Staged GitHub CLI config")
        else:
            print(f"  No GitHub CLI config found at {gh_config_dir}")

    if config.copy_agent_keys:
        source = os.path.join(gh_config_dir, "hosts.yml")
        destination = os.path.join(payload_dir, "secrets", "gh", "hosts.yml")
        if _copy_existing_path(source, destination):
            os.chmod(destination, 0o600)
            print("  Staged GitHub CLI credentials")
        else:
            print(f"  No GitHub CLI credentials found at {source}")


def prepare_agent_payload(config: SetupConfig, payload_dir: str) -> None:
    if not (config.copy_agent_config or config.copy_agent_keys):
        return

    selected_tools = config.install_gh or bool(config.selected_agent_tools())
    if not selected_tools:
        print("\nAgent config/key copy requested, but no agent tool flags were selected")
        return

    print(f"\n{'='*60}")
    print("Staging agent tool config and credentials...")
    print(f"{'='*60}")

    if config.dry_run:
        print("  [DRY RUN] Would stage selected agent tool config and credentials")
        return

    local_home = _local_user_home()
    os.makedirs(payload_dir, mode=0o700, exist_ok=True)

    if config.install_codex:
        _prepare_codex_payload(config, payload_dir, local_home)
    if config.install_claude:
        _prepare_claude_payload(config, payload_dir, local_home)
    if config.install_opencode:
        _prepare_opencode_payload(config, payload_dir, local_home)
    if config.install_gh:
        _prepare_github_cli_payload(config, payload_dir, local_home)


def create_tar_from_dir(source_dir: str) -> bytes:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
        tar.add(source_dir, arcname=".")
    return tar_buffer.getvalue()


def create_argument_parser(description: str, allow_steps: bool = False) -> argparse.ArgumentParser:
    return create_setup_argument_parser(description, for_remote=False, allow_steps=allow_steps)


def _expand_remote_args(remote_args: list[str]) -> list[str]:
    """Split quoted remote arg fragments back into argv tokens for subprocess usage."""
    expanded_args: list[str] = []
    for arg in remote_args:
        expanded_args.extend(shlex.split(arg))
    return expanded_args


def _write_remote_args_file(build_dir: str, remote_arg_tokens: list[str]) -> str:
    """Persist runtime argv tokens outside the process table."""
    args_path = os.path.join(build_dir, REMOTE_ARGS_FILENAME)
    with open(args_path, "w", encoding="utf-8") as file_obj:
        json.dump(remote_arg_tokens, file_obj)
        file_obj.write("\n")
    os.chmod(args_path, 0o600)
    return args_path


def _default_root_storage_for_host(host) -> Optional[str]:
    if host.default_storage:
        return host.default_storage
    if host.facts and host.facts.default_root_storage:
        return host.facts.default_root_storage
    return None


def _default_template_storage_for_host(host) -> Optional[str]:
    if host.default_template_storage:
        return host.default_template_storage
    if host.facts and host.facts.default_template_storage:
        return host.facts.default_template_storage
    return None


def _is_storage_amount(value: str) -> bool:
    try:
        validate_memory_string(value, "--storage AMOUNT")
    except ValueError:
        return False
    return True


def _apply_hosted_proxmox_defaults(
    config: SetupConfig,
    workspace: Optional[str],
) -> None:
    """Resolve saved Proxmox host details and expand shorthand storage specs."""
    if not config.hosted_node:
        return

    if config.machine_type == DEFAULT_MACHINE_TYPE:
        config.machine_type = "vm"

    host = find_proxmox_host(str(config.hosted_node), workspace)
    if host:
        if config.hosted_node == host.name:
            config.hosted_node = host.address
        if not config.hosted_key and host.ssh_key:
            config.hosted_key = host.ssh_key
        if not config.ssh_key and host.ssh_key:
            config.ssh_key = host.ssh_key

    storage_specs = _normalize_container_storage(config.container_storage)
    if not storage_specs:
        return

    root_pool = _default_root_storage_for_host(host) if host else None
    template_pool = _default_template_storage_for_host(host) if host else None
    root_pool = root_pool or "auto"
    template_pool = template_pool or "auto"
    updated_specs: list[list[str]] = []
    changed = False

    for spec in storage_specs:
        normalized = list(spec)
        if normalized and normalized[0] == "root":
            if len(normalized) == 2 and _is_storage_amount(normalized[1]):
                normalized = ["root", root_pool, normalized[1]]
                changed = True
            elif len(normalized) == 3 and normalized[1] in {"default", "host"}:
                normalized = ["root", root_pool, normalized[2]]
                changed = True
        elif normalized and normalized[0] == "template":
            if len(normalized) == 1:
                normalized = ["template", template_pool]
                changed = True
            elif len(normalized) == 2 and normalized[1] in {"default", "host"}:
                normalized = ["template", template_pool]
                changed = True
        updated_specs.append(normalized)

    if changed:
        config.container_storage = updated_specs


def prepare_validated_runtime_config(
    config: SetupConfig,
    workspace: Optional[str],
) -> SetupConfig:
    """Apply saved-host defaults, resolve credentials, and validate a setup."""
    _apply_hosted_proxmox_defaults(config, workspace)
    runtime_config = prepare_runtime_config(config, workspace)
    validate_timezone_name(runtime_config.timezone)
    validate_apt_packages(runtime_config.apt_packages)
    validate_agent_repositories(runtime_config.agent_repos)
    validate_notification_args(runtime_config.notify_specs)
    validate_ssl_email(runtime_config.ssl_email)
    validate_deploy_specs(runtime_config.deploy_specs)
    validate_deploy_targets(runtime_config.deploy_targets)
    validate_sync_specs(runtime_config.sync_specs)
    validate_scrub_specs(runtime_config.scrub_specs)
    validate_smb_mount_specs(runtime_config.smb_mounts)
    validate_samba_share_specs(
        runtime_config.samba_shares,
        runtime_config.share_credentials,
    )
    validate_gogs_settings(runtime_config.gogs)
    validate_antistatic_settings(runtime_config)
    validate_hosted_flags(runtime_config)
    validate_rdp_settings(runtime_config)
    validate_samba_share_credentials(runtime_config)
    return runtime_config


def register_proxmox_setup_host(
    config: SetupConfig,
    workspace: Optional[str] = None,
) -> None:
    """Register a successfully configured ``server_proxmox`` host."""
    if config.system_type != "server_proxmox" or config.dry_run:
        return

    host = ProxmoxHost(
        name=config.friendly_name or config.host,
        address=config.host,
        user="root",
        ssh_key=config.ssh_key,
    )
    registered = sync_proxmox_host(host, workspace)
    print(f"Registered Proxmox host '{registered.name}' ({registered.address}).")


def run_remote_setup(config: SetupConfig) -> int:
    is_local = config.host in ["localhost", "127.0.0.1"]
    
    if is_local and os.geteuid() != 0:
        print("Error: Local setup requires root privileges. Please run with sudo.")
        return 1

    build_dir = tempfile.mkdtemp(prefix="infra_setup_build_")
    try:
        copy_project_files(build_dir)
        
        if config.deploy_specs:
            deploy_dir = os.path.join(build_dir, "deployments")
            os.makedirs(deploy_dir, exist_ok=True)
            prepare_deployments(config, deploy_dir)

        if config.agent_repos:
            agent_repos_dir = os.path.join(build_dir, AGENT_REPOS_DIRNAME)
            os.makedirs(agent_repos_dir, exist_ok=True)
            prepare_agent_repositories(config, agent_repos_dir)

        if config.copy_agent_config or config.copy_agent_keys:
            agent_payload_dir = os.path.join(build_dir, AGENT_PAYLOAD_DIRNAME)
            prepare_agent_payload(config, agent_payload_dir)

        remote_arg_tokens = _expand_remote_args(config.to_remote_args())
        _write_remote_args_file(build_dir, remote_arg_tokens)
        remote_args_path = os.path.join(REMOTE_INSTALL_DIR, REMOTE_ARGS_FILENAME)
        command_tokens = [
            sys.executable,
            os.path.join(REMOTE_INSTALL_DIR, "remote_setup.py"),
            "--args-file",
            remote_args_path,
        ]
        
        if config.dry_run:
            print("\n" + "=" * 60)
            print("[DRY RUN] Would execute:")
            if is_local:
                print(f"  Copy files to {REMOTE_INSTALL_DIR}")
                print(f"  Run: {shlex.join(command_tokens)}")
            else:
                print(f"  Upload files to {config.host}:{REMOTE_INSTALL_DIR}")
                print(f"  Run: {shlex.join(command_tokens)}")
            print("=" * 60)
            return 0

        if is_local:
            print(f"\n{'='*60}")
            print("Running setup locally...")
            print(f"{'='*60}")
            
            if os.path.exists(REMOTE_INSTALL_DIR):
                shutil.rmtree(REMOTE_INSTALL_DIR)
            shutil.copytree(build_dir, REMOTE_INSTALL_DIR, symlinks=True)
            os.chmod(REMOTE_INSTALL_DIR, 0o755)
            
            env = os.environ.copy()
            env["LC_ALL"] = "C"
            
            try:
                process = subprocess.Popen(
                    command_tokens,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                    cwd=REMOTE_INSTALL_DIR
                )
                
                if process.stdout is not None:
                    for line in process.stdout:
                        print(line, end='', flush=True)
                    
                return process.wait()
            except Exception as e:
                print(f"Error running local setup: {e}")
                return 1
        else:
            tar_data = create_tar_from_dir(build_dir)
            
            remote_python = "python3"
            remote_script = os.path.join(REMOTE_INSTALL_DIR, "remote_setup.py")
            remote_cmd_args = [remote_python, remote_script, "--args-file", remote_args_path]
            remote_shell_cmd = chain_remote_commands(
                [
                    ["rm", "-rf", REMOTE_INSTALL_DIR],
                    ["mkdir", "-p", REMOTE_INSTALL_DIR],
                    ["cd", REMOTE_INSTALL_DIR],
                    ["tar", "xzf", "-"],
                    ["chmod", "0755", REMOTE_INSTALL_DIR],
                    remote_cmd_args,
                ]
            )
            ssh_cmd = build_ssh_command(
                config.host,
                "root",
                config.ssh_key,
                remote_command=remote_shell_cmd,
                connect_timeout=30,
                server_alive_interval=30,
            )
            
            ssh_env = os.environ.copy()
            ssh_env["LC_ALL"] = "C"
            
            try:
                process = subprocess.Popen(
                    ssh_cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=False,
                    bufsize=0,
                    env=ssh_env,
                )

                if process.stdin is not None:
                    process.stdin.write(tar_data)
                    process.stdin.close()

                if process.stdout is not None:
                    for line in io.TextIOWrapper(process.stdout, encoding='utf-8'):
                        print(line, end='', flush=True)

                return process.wait()
            except Exception as e:
                print(f"Error running remote setup: {e}")
                return 1

    finally:
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)


def setup_main(system_type: str, description: str, success_msg_fn: Callable[[SetupConfig], None]) -> int:
    allow_steps = (system_type == "custom_steps")
    parser = create_argument_parser(description, allow_steps)
    
    if argcomplete:
        argcomplete.autocomplete(parser)
    
    args = parser.parse_args()
    if getattr(args, 'workspace', None):
        try:
            validate_workspace_dir(args.workspace)
        except ValueError as e:
            print(f"Error: {e}")
            return 1
        set_workspace_dir(args.workspace)
    
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    config = SetupConfig.from_args(args, system_type)

    try:
        runtime_config = prepare_validated_runtime_config(
            config,
            getattr(args, "workspace", None),
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Hosted guest provisioning (if --hosted)
    if config.hosted_node:
        try:
            validate_hosted_flags(config)
        except ValueError as e:
            print(f"Error: {e}")
            return 1

        if config.machine_type == "vm":
            from lib.proxmox_vm import provision_vm, VMAlreadyExists

            print(f"\n{'='*60}")
            print(f"Provisioning VM on {config.hosted_node}...")
            print(f"{'='*60}")

            try:
                provision_vm(config, image=config.vm_image)
            except VMAlreadyExists:
                print("  ✓ VM already provisioned, skipping creation")
            except Exception as e:
                print(f"\n✗ Failed to provision VM: {e}")
                return 1
        else:
            from lib.proxmox_node import provision_container, ContainerAlreadyExists

            print(f"\n{'='*60}")
            print(f"Provisioning LXC container on {config.hosted_node}...")
            print(f"{'='*60}")

            try:
                provision_container(config)
            except ContainerAlreadyExists:
                print("  ✓ Container already provisioned, skipping creation")
            except Exception as e:
                print(f"\n✗ Failed to provision container: {e}")
                return 1

    print_setup_summary(config, description)
    
    if not config.dry_run:
        store_cli_credentials(config)
        save_setup_command(config, operation="setup")
    
    start_time = time.time()
    returncode = 1
    try:
        returncode = run_remote_setup(runtime_config)
    finally:
        end_time = time.time()
        success = (returncode == 0)
        if not config.dry_run:
            save_setup_command(config, start_time, end_time, success, operation="setup")
    
    if returncode != 0:
        print(f"\n✗ Setup failed (exit code: {returncode})")
        return 1

    try:
        register_proxmox_setup_host(config, getattr(args, "workspace", None))
    except ValueError as exc:
        print(f"\n✗ Setup completed, but Proxmox host registration failed: {exc}")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    success_msg_fn(config)
    print("=" * 60)
    
    return 0
