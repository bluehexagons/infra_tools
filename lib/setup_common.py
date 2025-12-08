#!/usr/bin/env python3

import argparse
import getpass
import hashlib
import io
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import json
from typing import Optional, Dict, List, Any


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "..", "remote_setup.py")
REMOTE_MODULES_DIR = os.path.join(SCRIPT_DIR, "..", "remote_modules")
SHARED_DIR = os.path.join(SCRIPT_DIR, "..", "shared")
REMOTE_INSTALL_DIR = "/opt/infra_tools"
GIT_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/git_repos")
SETUP_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/setups")


def validate_ip_address(ip: str) -> bool:
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    octets = ip.split('.')
    return all(0 <= int(octet) <= 255 for octet in octets)


def validate_host(host: str) -> bool:
    """Validate if host is a valid IP address or hostname."""
    normalized_host = host.lower().rstrip('.')
    if validate_ip_address(normalized_host):
        return True
    hostname_pattern = r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$'
    return bool(re.match(hostname_pattern, normalized_host))


def validate_username(username: str) -> bool:
    pattern = r'^[a-z_][a-z0-9_-]{0,31}$'
    return bool(re.match(pattern, username))


def get_local_timezone() -> str:
    if os.path.exists("/etc/timezone"):
        try:
            with open("/etc/timezone", "r") as f:
                tz = f.read().strip()
                if tz:
                    return tz
        except Exception:
            pass
    
    try:
        result = subprocess.run(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    
    if os.path.islink("/etc/localtime"):
        try:
            target = os.readlink("/etc/localtime")
            if "zoneinfo/" in target:
                tz = target.split("zoneinfo/", 1)[1]
                return tz
        except Exception:
            pass
    
    return "UTC"


def get_current_username() -> str:
    return getpass.getuser()


def get_cache_path_for_host(host: str) -> str:
    """Get the cache file path for a given host."""
    normalized_host = host.lower().rstrip('.')
    import hashlib
    host_hash = hashlib.sha256(normalized_host.encode()).hexdigest()[:8]
    safe_host = re.sub(r'[^a-zA-Z0-9._-]', '_', normalized_host)
    os.makedirs(SETUP_CACHE_DIR, exist_ok=True)
    return os.path.join(SETUP_CACHE_DIR, f"{safe_host}_{host_hash}.json")


def save_setup_command(host: str, system_type: str, args_dict: Dict[str, Any]) -> None:
    """Save the setup command for a host."""
    cache_path = get_cache_path_for_host(host)
    cache_data = {
        "host": host,
        "system_type": system_type,
        "args": args_dict,
        "script": f"setup_{system_type}.py"
    }
    with open(cache_path, 'w') as f:
        json.dump(cache_data, f, indent=2)


def load_setup_command(host: str) -> Optional[Dict[str, Any]]:
    """Load the cached setup command for a host."""
    cache_path = get_cache_path_for_host(host)
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load cached setup for {host}: {e}")
        return None


def merge_setup_args(cached_args: Dict[str, Any], new_args: Dict[str, Any]) -> Dict[str, Any]:
    """Merge cached args with new args, adding/modifying but not removing."""
    merged = cached_args.copy()
    
    for key, value in new_args.items():
        if key == 'deploy' and key in merged:
            if merged[key] is None:
                merged[key] = value
            elif value is not None:
                existing_deploys = {(spec, url) for spec, url in merged[key]}
                for deploy_spec, git_url in value:
                    deploy_tuple = (deploy_spec, git_url)
                    if deploy_tuple not in existing_deploys:
                        merged[key].append([deploy_spec, git_url])
                        existing_deploys.add(deploy_tuple)
        elif value is not None:
            if isinstance(value, bool) and value:
                merged[key] = value
            elif not isinstance(value, bool):
                merged[key] = value
    
    return merged


def clone_repository(git_url: str, temp_dir: str, cache_dir: Optional[str] = None, dry_run: bool = False) -> Optional[str]:
    """Clone or update a git repository, optionally using a local cache."""
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
        
        return clone_path
    else:
        print(f"  Cloning {git_url}...")
        if dry_run:
            print(f"  [DRY RUN] Would clone to {clone_path}")
            return clone_path
        
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
            return clone_path
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
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("ip", help="IP address of the remote host")
    parser.add_argument("username", nargs="?", default=None, 
                       help="Username (defaults to current user)")
    parser.add_argument("-k", "--key", help="SSH private key path")
    parser.add_argument("-p", "--password", help="User password")
    parser.add_argument("-t", "--timezone", help="Timezone (defaults to local)")
    if allow_steps:
        parser.add_argument("--steps", help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--skip-audio", action="store_true", 
                       help="Skip audio setup (desktop only)")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon"], default="xfce",
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--browser", choices=["brave", "firefox", "browsh", "vivaldi", "lynx"], default="brave",
                       help="Web browser to install (default: brave)")
    parser.add_argument("--flatpak", action="store_true",
                       help="Install desktop apps via Flatpak when available (non-containerized environments)")
    parser.add_argument("--office", action="store_true",
                       help="Install LibreOffice (desktop only)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")
    parser.add_argument("--ruby", action="store_true",
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", action="store_true",
                       help="Install latest Go version")
    parser.add_argument("--node", action="store_true",
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    parser.add_argument("--deploy", action="append", nargs=2, metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                       help="Deploy a git repository (domain.com/path or /path) to auto-configure nginx (can be used multiple times)")
    return parser


def run_remote_setup(
    ip: str,
    username: str,
    system_type: str,
    password: Optional[str] = None,
    ssh_key: Optional[str] = None,
    timezone: Optional[str] = None,
    skip_audio: bool = False,
    desktop: str = "xfce",
    browser: str = "brave",
    use_flatpak: bool = False,
    install_office: bool = False,
    dry_run: bool = False,
    install_ruby: bool = False,
    install_go: bool = False,
    install_node: bool = False,
    custom_steps: Optional[str] = None,
    deploy_specs: Optional[list] = None,
) -> int:
    try:
        tar_data = create_tar_archive()
    except FileNotFoundError as e:
        print(f"Error: Remote setup files not found: {e}")
        return 1
    
    ssh_opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=30",
        "-o", "ServerAliveInterval=30",
    ]
    if ssh_key:
        ssh_opts.extend(["-i", ssh_key])
    
    escaped_install_dir = shlex.quote(REMOTE_INSTALL_DIR)
    
    cmd_parts = [
        f"python3 {escaped_install_dir}/remote_setup.py",
        f"--system-type {shlex.quote(system_type)}",
        f"--username {shlex.quote(username)}",
    ]
    
    if password:
        cmd_parts.append(f"--password {shlex.quote(password)}")
    
    if timezone:
        cmd_parts.append(f"--timezone {shlex.quote(timezone)}")
    
    if skip_audio:
        cmd_parts.append("--skip-audio")
    
    if desktop != "xfce":
        cmd_parts.append(f"--desktop {shlex.quote(desktop)}")
    
    if browser != "brave":
        cmd_parts.append(f"--browser {shlex.quote(browser)}")
    
    if use_flatpak:
        cmd_parts.append("--flatpak")
    
    if install_office:
        cmd_parts.append("--office")
    
    if dry_run:
        cmd_parts.append("--dry-run")
    
    if install_ruby:
        cmd_parts.append("--ruby")
    
    if install_go:
        cmd_parts.append("--go")
    
    if install_node:
        cmd_parts.append("--node")
    
    if custom_steps:
        cmd_parts.append(f"--steps {shlex.quote(custom_steps)}")
    
    if deploy_specs:
        cmd_parts.append("--lite-deploy")
        for deploy_spec, git_url in deploy_specs:
            cmd_parts.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
    
    remote_cmd = f"""
mkdir -p {escaped_install_dir} && \
cd {escaped_install_dir} && \
tar xzf - && \
{' '.join(cmd_parts)}
"""
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{ip}", remote_cmd]
    
    # Handle deployments: clone repositories locally first
    temp_deploy_dir = None
    deploy_tar_data = None
    if deploy_specs:
        temp_deploy_dir = tempfile.mkdtemp(prefix="infra_deploy_")
        print(f"\n{'='*60}")
        print("Cloning repositories locally...")
        print(f"{'='*60}")
        
        cloned_repos = []
        for deploy_spec, git_url in deploy_specs:
            clone_path = clone_repository(git_url, temp_deploy_dir, cache_dir=GIT_CACHE_DIR, dry_run=dry_run)
            if clone_path:
                cloned_repos.append((deploy_spec, clone_path, git_url))
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
                for deploy_spec, clone_path, git_url in cloned_repos:
                    repo_name = os.path.basename(clone_path)
                    tar.add(clone_path, arcname=f"deployments/{repo_name}", filter=safe_filter)
            
            deploy_tar_data = deploy_tar_buffer.getvalue()
            print(f"  ✓ Packaged {len(cloned_repos)} repository(ies)")
    
    if dry_run:
        print("\n" + "=" * 60)
        print("[DRY RUN] Would execute:")
        print(f"  SSH command: {' '.join(ssh_cmd[:3])} root@{ip} ...")
        print(f"  Remote command: {' '.join(cmd_parts)}")
        if deploy_tar_data:
            print(f"  Would upload {len(deploy_tar_data)} bytes of deployment data")
        print("=" * 60)
        return 0
    
    try:
        process = subprocess.Popen(
            ssh_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            bufsize=0,
        )
        
        process.stdin.write(tar_data)
        process.stdin.close()
        
        for line in io.TextIOWrapper(process.stdout, encoding='utf-8'):
            print(line, end='', flush=True)
        
        returncode = process.wait()
        
        # Upload deployment repositories if setup succeeded
        if returncode == 0 and deploy_tar_data:
            print(f"\n{'='*60}")
            print("Uploading deployment repositories...")
            print(f"{'='*60}")
            
            # Simply extract to /opt/infra_tools/deployments/
            deploy_cmd = f"cd {escaped_install_dir} && tar xzf -"
            
            deploy_process = subprocess.Popen(
                ["ssh"] + ssh_opts + [f"root@{ip}", deploy_cmd],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
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
    
    if not validate_host(args.ip):
        print(f"Error: Invalid IP address or hostname: {args.ip}")
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
    
    timezone = args.timezone if args.timezone else get_local_timezone()
    
    print("=" * 60)
    print(f"{description}")
    print("=" * 60)
    print(f"Host: {args.ip}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    if args.skip_audio and system_type in ["workstation_desktop", "pc_dev"]:
        print("Skip audio: Yes")
    if hasattr(args, 'desktop') and args.desktop != "xfce" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Desktop: {args.desktop}")
    if hasattr(args, 'browser') and args.browser != "brave" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Browser: {args.browser}")
    if hasattr(args, 'flatpak') and args.flatpak and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Flatpak: Yes")
    if hasattr(args, 'office') and args.office and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Office: Yes")
    if hasattr(args, 'dry_run') and args.dry_run:
        print("Dry-run: Yes")
    if allow_steps and hasattr(args, 'steps') and args.steps:
        print(f"Steps: {args.steps}")
    if hasattr(args, 'deploy') and args.deploy:
        print(f"Deployments: {len(args.deploy)} repository(ies)")
        for location, git_url in args.deploy:
            print(f"  - {git_url} -> {location}")
    print("=" * 60)
    print()
    
    custom_steps = args.steps if allow_steps and hasattr(args, 'steps') else None
    desktop = args.desktop if hasattr(args, 'desktop') else "xfce"
    browser = args.browser if hasattr(args, 'browser') else "brave"
    use_flatpak = args.flatpak if hasattr(args, 'flatpak') else False
    # Default to installing LibreOffice for pc_dev unless explicitly disabled
    if system_type == "pc_dev":
        install_office = True if not hasattr(args, 'office') else args.office
    else:
        install_office = args.office if hasattr(args, 'office') else False
    dry_run = args.dry_run if hasattr(args, 'dry_run') else False
    deploy_specs = args.deploy if hasattr(args, 'deploy') and args.deploy else None
    
    # Save setup command for patching later (cache script name and args, not the script itself)
    args_dict = {
        'username': username,
        'password': args.password if args.password else None,
        'key': args.key if args.key else None,
        'timezone': timezone,
        'skip_audio': args.skip_audio,
        'desktop': desktop if hasattr(args, 'desktop') else None,
        'browser': browser if hasattr(args, 'browser') else None,
        'flatpak': use_flatpak if hasattr(args, 'flatpak') else None,
        'office': install_office if hasattr(args, 'office') else None,
        'ruby': args.ruby if hasattr(args, 'ruby') else False,
        'go': args.go if hasattr(args, 'go') else False,
        'node': args.node if hasattr(args, 'node') else False,
        'steps': custom_steps,
        'deploy': deploy_specs
    }
    if not dry_run:
        save_setup_command(args.ip, system_type, args_dict)
    
    returncode = run_remote_setup(
        args.ip, username, system_type, args.password, args.key, 
        timezone, args.skip_audio, desktop, browser, use_flatpak, install_office, dry_run, args.ruby, args.go, args.node, custom_steps, deploy_specs
    )
    
    if returncode != 0:
        print(f"\n✗ Setup failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    success_msg_fn(args.ip, username)
    print("=" * 60)
    
    return 0
