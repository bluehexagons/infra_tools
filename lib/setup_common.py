#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Optional, Callable

try:
    import argcomplete
except ImportError:
    argcomplete = None

from lib.config import SetupConfig
from lib.validators import validate_host, validate_username
from lib.system_utils import get_current_username
from lib.cache import save_setup_command
from lib.arg_parser import create_setup_argument_parser
from lib.display import print_setup_summary


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "..", "remote_setup.py")
LIB_DIR = SCRIPT_DIR
CONFIG_DIR = os.path.join(SCRIPT_DIR, "..", "config")
SERVICE_TOOLS_DIR = os.path.join(SCRIPT_DIR, "..", "service_tools")
REMOTE_INSTALL_DIR = "/opt/infra_tools"
GIT_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/git_repos")


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
    items_to_copy = ["remote_setup.py", "reconstruct_setup.py", "lib", "desktop", "web", "smb", "security", "sync", "common", "deploy"]
    
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
            
        cmd_parts = [shlex.quote(sys.executable), shlex.quote(os.path.join(REMOTE_INSTALL_DIR, "remote_setup.py"))] + config.to_remote_args()
        
        if config.dry_run:
            print("\n" + "=" * 60)
            print("[DRY RUN] Would execute:")
            if is_local:
                print(f"  Copy files to {REMOTE_INSTALL_DIR}")
                print(f"  Run: {' '.join(cmd_parts)}")
            else:
                print(f"  Upload files to {config.host}:{REMOTE_INSTALL_DIR}")
                print(f"  Run: {' '.join(cmd_parts)}")
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
                    ' '.join(cmd_parts),
                    shell=True,
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
            
            ssh_opts = [
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=30",
                "-o", "ServerAliveInterval=30",
            ]
            if config.ssh_key:
                ssh_opts.extend(["-i", config.ssh_key])
            
            escaped_install_dir = shlex.quote(REMOTE_INSTALL_DIR)
            
            remote_python = "python3"
            remote_script = os.path.join(REMOTE_INSTALL_DIR, "remote_setup.py")
            remote_cmd_args = [remote_python, remote_script] + config.to_remote_args()
            remote_cmd_str = ' '.join(remote_cmd_args)
            
            remote_shell_cmd = f"""
mkdir -p {escaped_install_dir} && \
cd {escaped_install_dir} && \
tar xzf - && \
{remote_cmd_str}
"""
            ssh_cmd = ["ssh"] + ssh_opts + [f"root@{config.host}", remote_shell_cmd]
            
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
    
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    config = SetupConfig.from_args(args, system_type)
    
    print_setup_summary(config, description)
    
    if not config.dry_run:
        save_setup_command(config)
    
    returncode = run_remote_setup(config)
    
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
