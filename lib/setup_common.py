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
    normalized_host = host.lower().rstrip('.')
    import hashlib
    host_hash = hashlib.sha256(normalized_host.encode()).hexdigest()[:8]
    safe_host = re.sub(r'[^a-zA-Z0-9._-]', '_', normalized_host)
    os.makedirs(SETUP_CACHE_DIR, exist_ok=True)
    return os.path.join(SETUP_CACHE_DIR, f"{safe_host}_{host_hash}.json")


def save_setup_command(host: str, system_type: str, args_dict: Dict[str, Any]) -> None:
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
    merged = cached_args.copy()
    
    for key, value in new_args.items():
        if key in ('deploy', 'deploy_specs') and key in merged:
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
            if isinstance(value, bool):
                merged[key] = value
            elif not isinstance(value, bool):
                merged[key] = value
    
    return merged


def clone_repository(git_url: str, temp_dir: str, cache_dir: Optional[str] = None, dry_run: bool = False) -> Optional[tuple]:
    """Clone repository and return (clone_path, commit_hash) tuple."""
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
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("host", help="IP address or hostname of the remote host")
    parser.add_argument("username", nargs="?", default=None, 
                       help="Username (defaults to current user)")
    parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
    parser.add_argument("-p", "--password", help="User password")
    parser.add_argument("-t", "--timezone", help="Timezone (defaults to local)")
    if allow_steps:
        parser.add_argument("--steps", dest="custom_steps", help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--skip-audio", action=argparse.BooleanOptionalAction, default=None,
                       help="Skip audio setup (desktop only)")
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon"], default=None,
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--browser", choices=["brave", "firefox", "browsh", "vivaldi", "lynx"], default=None,
                       help="Web browser to install (default: brave)")
    parser.add_argument("--flatpak", dest="use_flatpak", action=argparse.BooleanOptionalAction, default=None,
                       help="Install desktop apps via Flatpak when available (non-containerized environments)")
    parser.add_argument("--office", dest="install_office", action=argparse.BooleanOptionalAction, default=None,
                       help="Install LibreOffice (desktop only)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")
    parser.add_argument("--ruby", dest="install_ruby", action=argparse.BooleanOptionalAction, default=None,
                       help="Install rbenv + latest Ruby version")
    parser.add_argument("--go", dest="install_go", action=argparse.BooleanOptionalAction, default=None,
                       help="Install latest Go version")
    parser.add_argument("--node", dest="install_node", action=argparse.BooleanOptionalAction, default=None,
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    parser.add_argument("--deploy", dest="deploy_specs", action="append", nargs=2, metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                       help="Deploy a git repository (domain.com/path or /path) to auto-configure nginx (can be used multiple times)")
    parser.add_argument("--full-deploy", dest="full_deploy", action="store_true",
                       help="Always rebuild deployments even if they haven't changed (default: skip unchanged deployments)")
    parser.add_argument("--ssl", dest="enable_ssl", action=argparse.BooleanOptionalAction, default=None,
                       help="Enable Let's Encrypt SSL/TLS certificates for deployed domains")
    parser.add_argument("--ssl-email", dest="ssl_email",
                       help="Email address for Let's Encrypt registration (optional)")
    parser.add_argument("--cloudflare", dest="enable_cloudflare", action=argparse.BooleanOptionalAction, default=None,
                       help="Preconfigure server for Cloudflare tunnel (disables public HTTP/HTTPS ports)")
    parser.add_argument("--api-subdomain", dest="api_subdomain", action=argparse.BooleanOptionalAction, default=None,
                       help="Deploy Rails API as a subdomain (api.domain.com) instead of a subdirectory (domain.com/api)")
    return parser


def run_remote_setup(
    host: str,
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
    full_deploy: bool = False,
    enable_ssl: bool = False,
    ssl_email: Optional[str] = None,
    enable_cloudflare: bool = False,
    api_subdomain: bool = False,
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
    
    if desktop and desktop != "xfce":
        cmd_parts.append(f"--desktop {shlex.quote(desktop)}")
    
    if browser and browser != "brave":
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
        if full_deploy:
            cmd_parts.append("--full-deploy")
        for deploy_spec, git_url in deploy_specs:
            cmd_parts.append(f"--deploy {shlex.quote(deploy_spec)} {shlex.quote(git_url)}")
    
    if enable_ssl:
        cmd_parts.append("--ssl")
        if ssl_email:
            cmd_parts.append(f"--ssl-email {shlex.quote(ssl_email)}")
    
    if enable_cloudflare:
        cmd_parts.append("--cloudflare")
    
    if api_subdomain:
        cmd_parts.append("--api-subdomain")
    
    remote_cmd = f"""
mkdir -p {escaped_install_dir} && \
cd {escaped_install_dir} && \
tar xzf - && \
{' '.join(cmd_parts)}
"""
    
    ssh_cmd = ["ssh"] + ssh_opts + [f"root@{host}", remote_cmd]
    
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
            result = clone_repository(git_url, temp_deploy_dir, cache_dir=GIT_CACHE_DIR, dry_run=dry_run)
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
    
    if dry_run:
        print("\n" + "=" * 60)
        print("[DRY RUN] Would execute:")
        print(f"  SSH command: {' '.join(ssh_cmd[:3])} root@{host} ...")
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
                ["ssh"] + ssh_opts + [f"root@{host}", deploy_cmd],
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
    
    timezone = args.timezone if args.timezone else get_local_timezone()
    
    print("=" * 60)
    print(f"{description}")
    print("=" * 60)
    print(f"Host: {args.host}")
    print(f"User: {username}")
    print(f"Timezone: {timezone}")
    if args.skip_audio and system_type in ["workstation_desktop", "pc_dev"]:
        print("Skip audio: Yes")
    if args.desktop and args.desktop != "xfce" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Desktop: {args.desktop}")
    if args.browser and args.browser != "brave" and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print(f"Browser: {args.browser}")
    if args.use_flatpak and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Flatpak: Yes")
    if args.install_office and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
        print("Office: Yes")
    if args.dry_run:
        print("Dry-run: Yes")
    if allow_steps and args.custom_steps:
        print(f"Steps: {args.custom_steps}")
    if args.deploy_specs:
        print(f"Deployments: {len(args.deploy_specs)} repository(ies)")
        for location, git_url in args.deploy_specs:
            print(f"  - {git_url} -> {location}")
        if args.full_deploy:
            print("Full deploy: Yes (rebuild all deployments)")
        else:
            print("Full deploy: No (skip unchanged deployments)")
        if args.enable_ssl:
            print("SSL: Yes (Let's Encrypt)")
            if args.ssl_email:
                print(f"SSL Email: {args.ssl_email}")
        if args.enable_cloudflare:
            print("Cloudflare: Yes (tunnel preconfiguration)")
    print("=" * 60)
    print()
    
    # Handle defaults
    desktop = args.desktop or "xfce"
    browser = args.browser or "brave"
    
    install_office = args.install_office
    if system_type == "pc_dev" and not install_office:
        install_office = True
    
    args_dict = vars(args).copy()
    if 'host' in args_dict:
        del args_dict['host']
    
    args_dict['username'] = username
    args_dict['timezone'] = timezone
    args_dict['desktop'] = desktop
    args_dict['browser'] = browser
    args_dict['install_office'] = install_office
    
    if not args.dry_run:
        save_setup_command(args.host, system_type, args_dict)
    
    returncode = run_remote_setup(
        host=args.host,
        username=username,
        system_type=system_type,
        password=args.password,
        ssh_key=args.ssh_key,
        timezone=timezone,
        skip_audio=args.skip_audio,
        desktop=desktop,
        browser=browser,
        use_flatpak=args.use_flatpak,
        install_office=install_office,
        dry_run=args.dry_run,
        install_ruby=args.install_ruby,
        install_go=args.install_go,
        install_node=args.install_node,
        custom_steps=args.custom_steps if allow_steps else None,
        deploy_specs=args.deploy_specs,
        full_deploy=args.full_deploy if args.deploy_specs else False,
        enable_ssl=args.enable_ssl if args.deploy_specs else False,
        ssl_email=args.ssl_email if args.enable_ssl else None,
        enable_cloudflare=args.enable_cloudflare or False,
        api_subdomain=args.api_subdomain or False
    )
    
    if returncode != 0:
        print(f"\n✗ Setup failed (exit code: {returncode})")
        return 1
    
    print()
    print("=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    success_msg_fn(args.host, username)
    print("=" * 60)
    
    return 0
