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
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "..", "remote_setup.py")
REMOTE_MODULES_DIR = os.path.join(SCRIPT_DIR, "..", "remote_modules")
SHARED_DIR = os.path.join(SCRIPT_DIR, "..", "shared")
REMOTE_INSTALL_DIR = "/opt/infra_tools"
GIT_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/git_repos")
SETUP_CACHE_DIR = os.path.expanduser("~/.cache/infra_tools/setups")


@dataclass
class SetupConfig:
    """Configuration for a setup operation."""
    host: str
    username: str
    system_type: str
    password: Optional[str] = None
    ssh_key: Optional[str] = None
    timezone: str = "UTC"
    friendly_name: Optional[str] = None
    tags: Optional[List[str]] = None
    enable_rdp: bool = False
    enable_x2go: bool = False
    skip_audio: bool = False
    desktop: str = "xfce"
    browser: str = "brave"
    use_flatpak: bool = False
    install_office: bool = False
    dry_run: bool = False
    install_ruby: bool = False
    install_go: bool = False
    install_node: bool = False
    custom_steps: Optional[str] = None
    deploy_specs: Optional[List[List[str]]] = None
    full_deploy: bool = False
    enable_ssl: bool = False
    ssl_email: Optional[str] = None
    enable_cloudflare: bool = False
    api_subdomain: bool = False
    enable_samba: bool = False
    samba_shares: Optional[List[List[str]]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding host and system_type."""
        data = asdict(self)
        data.pop('host', None)
        data.pop('system_type', None)
        # Convert tags list to comma-separated string for storage
        if self.tags:
            data['tags'] = ','.join(self.tags)
        return data
    
    @classmethod
    def from_dict(cls, host: str, system_type: str, data: Dict[str, Any]) -> 'SetupConfig':
        """Create SetupConfig from dictionary."""
        # Convert tags string to list
        tags_str = data.get('tags')
        if tags_str and isinstance(tags_str, str):
            data['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
        elif not tags_str:
            data['tags'] = None
            
        # Handle friendly_name
        if 'friendly_name' not in data:
            data['friendly_name'] = None
            
        return cls(host=host, system_type=system_type, **data)
    
    @classmethod
    def from_args(cls, args: argparse.Namespace, system_type: str) -> 'SetupConfig':
        """Create SetupConfig from parsed arguments."""
        # Extract and process tags
        tags = None
        if args.tags:
            tags = [tag.strip() for tag in args.tags.split(',') if tag.strip()]
        
        # Get username with default
        username = args.username if args.username else get_current_username()
        
        # Get timezone with default
        timezone = args.timezone if args.timezone else get_local_timezone()
        
        # Handle defaults for desktop and browser
        desktop = args.desktop or "xfce"
        browser = args.browser or "brave"
        
        # Handle office default for pc_dev
        install_office = args.install_office
        if system_type == "pc_dev" and install_office is None:
            install_office = True
        elif install_office is None:
            install_office = False
        
        # Handle RDP default
        enable_rdp = args.enable_rdp
        if enable_rdp is None and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
            enable_rdp = True
        elif enable_rdp is None:
            enable_rdp = False
        
        # Handle X2Go default
        enable_x2go = args.enable_x2go
        if enable_x2go is None and system_type in ["workstation_desktop", "pc_dev", "workstation_dev"]:
            enable_x2go = True
        elif enable_x2go is None:
            enable_x2go = False
        
        return cls(
            host=args.host,
            username=username,
            system_type=system_type,
            password=getattr(args, 'password', None),
            ssh_key=getattr(args, 'ssh_key', None),
            timezone=timezone,
            friendly_name=getattr(args, 'friendly_name', None),
            tags=tags,
            enable_rdp=enable_rdp,
            enable_x2go=enable_x2go,
            skip_audio=getattr(args, 'skip_audio', False) or False,
            desktop=desktop,
            browser=browser,
            use_flatpak=getattr(args, 'use_flatpak', False) or False,
            install_office=install_office,
            dry_run=getattr(args, 'dry_run', False),
            install_ruby=getattr(args, 'install_ruby', False) or False,
            install_go=getattr(args, 'install_go', False) or False,
            install_node=getattr(args, 'install_node', False) or False,
            custom_steps=getattr(args, 'custom_steps', None),
            deploy_specs=getattr(args, 'deploy_specs', None),
            full_deploy=getattr(args, 'full_deploy', False),
            enable_ssl=getattr(args, 'enable_ssl', False) or False,
            ssl_email=getattr(args, 'ssl_email', None),
            enable_cloudflare=getattr(args, 'enable_cloudflare', False) or False,
            api_subdomain=getattr(args, 'api_subdomain', False) or False,
            enable_samba=getattr(args, 'enable_samba', False) or False,
            samba_shares=getattr(args, 'samba_shares', None)
        )


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


def print_name_and_tags(config: SetupConfig) -> None:
    """Print configuration name and tags if present."""
    if config.friendly_name:
        print(f"Name: {config.friendly_name}")
    if config.tags and len(config.tags) > 0:
        print(f"Tags: {', '.join(config.tags)}")


def print_success_header(config: SetupConfig) -> None:
    """Print common success information for all setup scripts."""
    print(f"Host: {config.host}")
    print(f"Username: {config.username}")
    if config.friendly_name or config.tags:
        print()
        print_name_and_tags(config)


def print_rdp_x2go_info(config: SetupConfig) -> None:
    """Print RDP and X2Go connection information."""
    if config.enable_rdp:
        print(f"RDP: {config.host}:3389")
        print(f"  Client: Remmina, Microsoft Remote Desktop")
    if config.enable_x2go:
        print(f"X2Go: {config.host}:22 (SSH)")
        print(f"  Client: x2goclient, Session: XFCE")


def get_cache_path_for_host(host: str) -> str:
    normalized_host = host.lower().rstrip('.')
    import hashlib
    host_hash = hashlib.sha256(normalized_host.encode()).hexdigest()[:8]
    safe_host = re.sub(r'[^a-zA-Z0-9._-]', '_', normalized_host)
    os.makedirs(SETUP_CACHE_DIR, exist_ok=True)
    return os.path.join(SETUP_CACHE_DIR, f"{safe_host}_{host_hash}.json")


def save_setup_command(config: SetupConfig) -> None:
    """Save setup configuration to cache."""
    cache_path = get_cache_path_for_host(config.host)
    
    cache_data = {
        "host": config.host,
        "system_type": config.system_type,
        "args": config.to_dict(),
        "script": f"setup_{config.system_type}.py"
    }
    
    # Add name and tags at top level for easier access
    if config.friendly_name:
        cache_data["name"] = config.friendly_name
    if config.tags:
        cache_data["tags"] = config.tags
    
    with open(cache_path, 'w') as f:
        json.dump(cache_data, f, indent=2)


def load_setup_command(host: str) -> Optional[SetupConfig]:
    """Load setup configuration from cache."""
    cache_path = get_cache_path_for_host(host)
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, 'r') as f:
            data = json.load(f)
            system_type = data.get('system_type')
            args_dict = data.get('args', {})
            return SetupConfig.from_dict(host, system_type, args_dict)
    except Exception as e:
        print(f"Warning: Failed to load cached setup for {host}: {e}")
        return None


def merge_setup_configs(cached_config: SetupConfig, new_config: SetupConfig) -> SetupConfig:
    """Merge two SetupConfig objects, with new_config taking precedence."""
    merged_dict = asdict(cached_config)
    new_dict = asdict(new_config)
    
    for key, value in new_dict.items():
        # Skip host and system_type as they should remain from cached
        if key in ('host', 'system_type'):
            continue
            
        # Handle deploy_specs merging
        if key == 'deploy_specs' and key in merged_dict:
            if merged_dict[key] is None:
                merged_dict[key] = value
            elif value is not None:
                existing_deploys = {(spec[0], spec[1]) for spec in merged_dict[key]}
                for deploy_spec in value:
                    deploy_tuple = (deploy_spec[0], deploy_spec[1])
                    if deploy_tuple not in existing_deploys:
                        merged_dict[key].append(deploy_spec)
                        existing_deploys.add(deploy_tuple)
        # Handle samba_shares merging
        elif key == 'samba_shares' and key in merged_dict:
            if merged_dict[key] is None:
                merged_dict[key] = value
            elif value is not None:
                existing_shares = {tuple(share) for share in merged_dict[key]}
                for share_spec in value:
                    share_tuple = tuple(share_spec)
                    if share_tuple not in existing_shares:
                        merged_dict[key].append(share_spec)
                        existing_shares.add(share_tuple)
        # Handle tags merging
        elif key == 'tags':
            if value is not None:
                merged_dict[key] = value
        # For all other fields, new value takes precedence if not None
        elif value is not None:
            merged_dict[key] = value
    
    return SetupConfig(**merged_dict)


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
    parser.add_argument("--name", dest="friendly_name", help="Friendly name for this configuration")
    parser.add_argument("--tags", dest="tags", help="Comma-separated list of tags for this configuration")
    if allow_steps:
        parser.add_argument("--steps", dest="custom_steps", help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--rdp", dest="enable_rdp", action=argparse.BooleanOptionalAction, default=None,
                       help="Enable RDP/XRDP setup (default: enabled for workstation setups)")
    parser.add_argument("--x2go", dest="enable_x2go", action=argparse.BooleanOptionalAction, default=None,
                       help="Enable X2Go remote desktop access (default: enabled for workstation setups)")
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
    parser.add_argument("--samba", dest="enable_samba", action=argparse.BooleanOptionalAction, default=None,
                       help="Install and configure Samba for SMB file sharing")
    parser.add_argument("--share", dest="samba_shares", action="append", nargs=4, metavar=("ACCESS_TYPE", "SHARE_NAME", "PATHS", "USERS"),
                       help="Configure Samba share: access_type (read|write), share_name, comma-separated paths, comma-separated username:password pairs (can be used multiple times)")
    return parser


def run_remote_setup(config: SetupConfig) -> int:
    """Execute remote setup with the given configuration."""
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
