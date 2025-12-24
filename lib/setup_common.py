#!/usr/bin/env python3

import argparse
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Optional

from lib.config import SetupConfig
from lib.validators import validate_host, validate_username
from lib.system_utils import get_current_username
from lib.cache import save_setup_command
from lib.arg_parser import create_setup_argument_parser


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "..", "remote_setup.py")
REMOTE_MODULES_DIR = os.path.join(SCRIPT_DIR, "..", "remote_modules")
SHARED_DIR = os.path.join(SCRIPT_DIR, "..", "shared")
REMOTE_INSTALL_DIR = "/opt/infra_tools"
GIT_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/git_repos")


def clone_repository(git_url: str, temp_dir: str, cache_dir: Optional[str] = None, dry_run: bool = False) -> Optional[tuple]:
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
                    
                    # Get the default branch from the remote
                    result = subprocess.run(
                        ["git", "-C", cache_path, "symbolic-ref", "refs/remotes/origin/HEAD", "--short"],
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result.returncode == 0:
                        default_branch = result.stdout.strip()
                    else:
                        # Fallback: try common default branches
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
        
        # Get commit hash
        commit_hash = None
        if not dry_run:
            from shared.deploy_utils import get_git_commit_hash
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
            
            # Get commit hash
            from shared.deploy_utils import get_git_commit_hash
            commit_hash = get_git_commit_hash(clone_path)
            
            return (clone_path, commit_hash)
        except Exception as e:
            print(f"  Error cloning repository: {e}")
            return None


def create_tar_archive() -> bytes:
    tar_buffer = io.BytesIO()
    
    def safe_filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        tarinfo.name = os.path.normpath(tarinfo.name)
        if tarinfo.name.startswith('..') or tarinfo.name.startswith('/'):
            return None
        return tarinfo
    
    with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
        tar.add(REMOTE_SCRIPT_PATH, arcname="remote_setup.py", filter=safe_filter)
        tar.add(REMOTE_MODULES_DIR, arcname="remote_modules", filter=safe_filter)
        tar.add(SHARED_DIR, arcname="shared", filter=safe_filter)
    
    return tar_buffer.getvalue()


def create_argument_parser(description: str, allow_steps: bool = False) -> argparse.ArgumentParser:
    return create_setup_argument_parser(description, for_remote=False, allow_steps=allow_steps)


def run_remote_setup(config: SetupConfig) -> int:
    try:
        tar_data = create_tar_archive()
    except FileNotFoundError as e:
        print(f"Error: Remote setup files not found: {e}")
        return 1
    
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if config.ssh_key:
        ssh_opts.extend(["-i", config.ssh_key])
    
    escaped_install_dir = shlex.quote(REMOTE_INSTALL_DIR)
    
    cmd_parts = [
        f"python3 {escaped_install_dir}/remote_setup.py",
        f"--system-type {shlex.quote(config.system_type)}",
        f"--username {shlex.quote(config.username)}",
    ]
    
    if config.password:
        cmd_parts.append(f"--password {shlex.quote(config.password)}")
    
    if config.timezone:
        cmd_parts.append(f"--timezone {shlex.quote(config.timezone)}")
    
    if config.enable_rdp:
        cmd_parts.append("--rdp")
    
    if config.enable_x2go:
        cmd_parts.append("--x2go")
    
    if config.skip_audio:
        cmd_parts.append("--skip-audio")
    
    if config.desktop and config.desktop != "xfce":
        cmd_parts.append(f"--desktop {shlex.quote(config.desktop)}")
    
    if config.browser and config.browser != "brave":
        cmd_parts.append(f"--browser {shlex.quote(config.browser)}")
    
    if config.use_flatpak:
        cmd_parts.append("--flatpak")
    
    if config.install_office:
        cmd_parts.append("--office")
    
    if config.dry_run:
        cmd_parts.append("--dry-run")
    
    if config.install_ruby:
        cmd_parts.append("--ruby")
    
    if config.install_go:
        cmd_parts.append("--go")
    
    if config.install_node:
        cmd_parts.append("--node")
    
    if config.custom_steps:
        cmd_parts.append(f"--steps {shlex.quote(config.custom_steps)}")
    
    if config.deploy_specs:
        cmd_parts.append("--lite-deploy")
        if config.full_deploy:
            cmd_parts.append("--full-deploy")
        for deploy_spec, git_url in config.deploy_specs:
            cmd_parts.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
    
    if config.enable_ssl:
        cmd_parts.append("--ssl")
        if config.ssl_email:
            cmd_parts.append(f"--ssl-email {shlex.quote(config.ssl_email)}")
    
    if config.enable_cloudflare:
        cmd_parts.append("--cloudflare")
    
    if config.api_subdomain:
        cmd_parts.append("--api-subdomain")
    
    if config.enable_samba:
        cmd_parts.append("--samba")
    
    if config.samba_shares:
        for share_spec in config.samba_shares:
            escaped_spec = ' '.join(shlex.quote(str(s)) for s in share_spec)
            cmd_parts.append(f"--share {escaped_spec}")
    
    remote_cmd = f"""
mkdir -p {escaped_install_dir} && \
cd {escaped_install_dir} && \
tar xzf - && \
{' '.join(cmd_parts)}
"""
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{config.host}", remote_cmd]
    
    # Handle deployments: clone repositories locally first
    temp_deploy_dir = None
    deploy_tar_data = None
    if config.deploy_specs:
        temp_deploy_dir = tempfile.mkdtemp(prefix="infra_deploy_")
        print(f"\n{'='*60}")
        print("Cloning repositories locally...")
        print(f"{'='*60}")
        
        cloned_repos = []
        for deploy_spec, git_url in config.deploy_specs:
            result = clone_repository(git_url, temp_deploy_dir, cache_dir=GIT_CACHE_DIR, dry_run=config.dry_run)
            if result:
                clone_path, commit_hash = result
                cloned_repos.append((deploy_spec, clone_path, git_url, commit_hash))
            else:
                print(f"Warning: Failed to clone {git_url}, skipping...")
        
        if cloned_repos:
            print(f"\n{'='*60}")
            print("Packaging repositories for upload...")
            print(f"{'='*60}")
            deploy_tar_buffer = io.BytesIO()
            
            def safe_filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
                tarinfo.name = os.path.normpath(tarinfo.name)
                if tarinfo.name.startswith('..') or tarinfo.name.startswith('/'):
                    return None
                # Exclude .git directory to save space
                if '/.git/' in tarinfo.name or tarinfo.name.endswith('/.git'):
                    return None
                return tarinfo
            
            with tarfile.open(fileobj=deploy_tar_buffer, mode='w:gz') as tar:
                for deploy_spec, clone_path, git_url, commit_hash in cloned_repos:
                    repo_name = os.path.basename(clone_path)
                    tar.add(clone_path, arcname=f"deployments/{repo_name}", filter=safe_filter)
                    
                    # Add commit hash metadata file
                    if commit_hash:
                        commit_info = tarfile.TarInfo(name=f"deployments/{repo_name}.commit")
                        commit_data = commit_hash.encode('utf-8')
                        commit_info.size = len(commit_data)
                        tar.addfile(commit_info, io.BytesIO(commit_data))
            
            deploy_tar_data = deploy_tar_buffer.getvalue()
            print(f"  ✓ Packaged {len(cloned_repos)} repository(ies)")
    
    if config.dry_run:
        print("\n" + "=" * 60)
        print("[DRY RUN] Would execute:")
        print(f"  SSH command: {' '.join(ssh_cmd[:3])} root@{config.host} ...")
        print(f"  Remote command: {' '.join(cmd_parts)}")
        if deploy_tar_data:
            print(f"  Would upload {len(deploy_tar_data)} bytes of deployment data")
        print("=" * 60)
        return 0
    
    ssh_env = os.environ.copy()
    ssh_env["LC_ALL"] = "C"

    try:
        # If we have deployment repositories to upload, send them first so
        # the remote `remote_setup.py --lite-deploy` run can find
        # /opt/infra_tools/deployments/<repo> while executing.
        if deploy_tar_data:
            print(f"\n{'='*60}")
            print("Uploading deployment repositories...")
            print(f"{'='*60}")

            deploy_cmd = f"mkdir -p {escaped_install_dir} && cd {escaped_install_dir} && tar xzf -"

            deploy_process = subprocess.Popen(
                ["ssh"] + ssh_opts + [f"root@{config.host}", deploy_cmd],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
                env=ssh_env,
            )

            deploy_process.stdin.write(deploy_tar_data)
            deploy_process.stdin.close()

            for line in io.TextIOWrapper(deploy_process.stdout, encoding='utf-8'):
                print(line, end='', flush=True)

            deploy_returncode = deploy_process.wait()
            if deploy_returncode != 0:
                print(f"Warning: Repository upload returned non-zero exit code: {deploy_returncode}")
            else:
                print(f"  ✓ Uploaded {len(cloned_repos)} repository(ies)")

        # Run the main remote setup (install remote files and execute script)
        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
            env=ssh_env,
        )

        process.stdin.write(tar_data)
        process.stdin.close()

        for line in io.TextIOWrapper(process.stdout, encoding='utf-8'):
            print(line, end='', flush=True)

        returncode = process.wait()

        return returncode
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        if temp_deploy_dir and os.path.exists(temp_deploy_dir):
            shutil.rmtree(temp_deploy_dir)


def setup_main(system_type: str, description: str, success_msg_fn) -> int:
    allow_steps = (system_type == "custom_steps")
    parser = create_argument_parser(description, allow_steps)
    args = parser.parse_args()
    
    if not validate_host(args.host):
        print(f"Error: Invalid IP address or hostname: {args.host}")
        return 1
    
    username = args.username if args.username else get_current_username()
    
    if not validate_username(username):
        print(f"Error: Invalid username: {username}")
        return 1
    
    if not os.path.exists(REMOTE_SCRIPT_PATH):
        print(f"Error: Remote setup script not found: {REMOTE_SCRIPT_PATH}")
        return 1
    
    if not os.path.exists(REMOTE_MODULES_DIR):
        print(f"Error: Remote modules not found: {REMOTE_MODULES_DIR}")
        return 1
    
    # Create SetupConfig from arguments
    config = SetupConfig.from_args(args, system_type)
    
    # Print setup information
    print("=" * 60)
    print(f"{description}")
    print("=" * 60)
    print(f"Host: {config.host}")
    print(f"User: {config.username}")
    print(f"Timezone: {config.timezone}")
    if system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"RDP: {'Yes' if config.enable_rdp else 'No'}")
        print(f"X2Go: {'Yes' if config.enable_x2go else 'No'}")
    elif args.enable_rdp is not None and system_type == "server_dev":
        print(f"RDP: {'Yes' if config.enable_rdp else 'No'}")
    if args.enable_x2go is not None and system_type == "server_dev":
        print(f"X2Go: {'Yes' if config.enable_x2go else 'No'}")
    if config.skip_audio and system_type in ["workstation_desktop", "pc_dev"]:
        print("Skip audio: Yes")
    if config.desktop and config.desktop != "xfce" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Desktop: {config.desktop}")
    if config.browser and config.browser != "brave" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Browser: {config.browser}")
    if config.use_flatpak and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Flatpak: Yes")
    if config.install_office and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Office: Yes")
    if config.dry_run:
        print("Dry-run: Yes")
    if allow_steps and config.custom_steps:
        print(f"Steps: {config.custom_steps}")
    if config.deploy_specs:
        print(f"Deployments: {len(config.deploy_specs)} repository(ies)")
        for location, git_url in config.deploy_specs:
            print(f"  - {git_url} -> {location}")
        if config.full_deploy:
            print("Full deploy: Yes (rebuild all deployments)")
        else:
            print("Full deploy: No (skip unchanged deployments)")
        if config.enable_ssl:
            print("SSL: Yes (Let's Encrypt)")
            if config.ssl_email:
                print(f"SSL Email: {config.ssl_email}")
        if config.enable_cloudflare:
            print("Cloudflare: Yes (tunnel preconfiguration)")
    if config.enable_samba:
        print("Samba: Yes")
        if config.samba_shares:
            print(f"Samba Shares: {len(config.samba_shares)} share(s)")
            for share in config.samba_shares:
                print(f"  - {share[1]}_{share[0]}: {share[2]}")
    print("=" * 60)
    print()
    
    # Save configuration before running
    if not config.dry_run:
        save_setup_command(config)
    
    # Run remote setup
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
