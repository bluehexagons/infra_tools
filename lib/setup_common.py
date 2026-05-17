#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
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

from lib.config import SetupConfig
from lib.credentials import prepare_runtime_config, store_cli_credentials
from lib.validators import validate_host, validate_username
from lib.validation import (
    validate_apt_packages,
    validate_deploy_specs,
    validate_deploy_targets,
    validate_hosted_flags,
    validate_samba_share_credentials,
    validate_samba_share_specs,
    validate_smb_mount_specs,
    validate_scrub_specs,
    validate_ssl_email,
    validate_sync_specs,
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


def clone_repository(git_url: str, temp_dir: str, cache_dir: Optional[str] = None, dry_run: bool = False) -> Optional[tuple[str, Optional[str]]]:
    repo_name = git_url.rstrip('/').split('/')[-1]
    if repo_name.endswith('.git'):
        repo_name = repo_name[:-4]
    
    clone_path = os.path.join(temp_dir, repo_name)
    
    if cache_dir:
        cache_path = os.path.join(cache_dir, repo_name)
        
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
                    ["mkdir", "-p", REMOTE_INSTALL_DIR],
                    ["cd", REMOTE_INSTALL_DIR],
                    ["tar", "xzf", "-"],
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
        runtime_config = prepare_runtime_config(config)
        validate_timezone_name(runtime_config.timezone)
        validate_apt_packages(runtime_config.apt_packages)
        validate_notification_args(runtime_config.notify_specs)
        validate_ssl_email(runtime_config.ssl_email)
        validate_deploy_specs(runtime_config.deploy_specs)
        validate_deploy_targets(runtime_config.deploy_targets)
        validate_sync_specs(runtime_config.sync_specs)
        validate_scrub_specs(runtime_config.scrub_specs)
        validate_smb_mount_specs(runtime_config.smb_mounts)
        validate_samba_share_specs(runtime_config.samba_shares, runtime_config.share_credentials)
        validate_samba_share_credentials(runtime_config)
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
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    success_msg_fn(config)
    print("=" * 60)
    
    return 0
