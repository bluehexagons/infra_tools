#!/usr/bin/env python3

from __future__ import annotations

import argparse


from lib.config import AGENT_SUITES, MACHINE_TYPES
from lib.plugin_registry import get_system_type_names


class _DeploySpecActionBase(argparse.Action):
    """Base class for parsing deployment spec/repository pairs."""
    flag_name = "--deploy"
    set_deploy_latest = False

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | list[str],
        option_string: str | None = None,
    ) -> None:
        raw_values = [values] if isinstance(values, str) else values
        if len(raw_values) % 2 != 0:
            parser.error(f"{self.flag_name} requires DOMAIN_OR_PATH and GIT_URL pairs")

        if self.set_deploy_latest:
            setattr(namespace, "deploy_latest", True)

        deploy_specs = list(getattr(namespace, "deploy_specs", None) or [])
        for index in range(0, len(raw_values), 2):
            deploy_specs.append([raw_values[index], raw_values[index + 1]])
        setattr(namespace, "deploy_specs", deploy_specs)


class DeploySpecAction(_DeploySpecActionBase):
    """Parse deployment specs for --deploy flag."""
    pass


class DeployLatestSpecAction(_DeploySpecActionBase):
    """Parse deployment specs for --deploy-latest flag, also enabling latest-version policy."""
    flag_name = "--deploy-latest"
    set_deploy_latest = True


def add_setup_arguments(
    parser: argparse.ArgumentParser,
    for_remote: bool = False,
    allow_steps: bool = False,
    include_system_type: bool = False,
    include_host: bool = True,
) -> None:
    """Add the shared setup/patch argument surface to an argparse parser."""

    if not for_remote:
        if include_system_type:
            parser.add_argument(
                "system_type",
                choices=get_system_type_names(),
                help="Type of system to set up",
            )
        if include_host:
            parser.add_argument("host", help="IP address or hostname of the remote host")
            parser.add_argument("username", nargs="?", default=None,
                               help="Username (defaults to current user)")
        parser.add_argument("-k", "--key", dest="ssh_key", help="SSH private key path")
        parser.add_argument(
            "--workspace",
            help="Workspace root for saved setups, credentials, known_hosts, and history"
        )
    
    parser.add_argument("-p", "--password", help="User password")
    parser.add_argument("-t", "--timezone", help="Timezone (defaults to UTC)")
    parser.add_argument("--machine", dest="machine_type",
                       choices=MACHINE_TYPES,
                       default=None,
                       help="Machine type override. Defaults to auto-detection "
                            "on the target; hosted Proxmox setup defaults to a VM.")
    
    if not for_remote:
        parser.add_argument("--name", dest="friendly_name", help="Friendly name for this configuration")
        parser.add_argument("--tags", dest="tags", help="Comma-separated list of tags for this configuration")

        # Hosted guest provisioning (Proxmox VM/LXC creation)
        parser.add_argument("--hosted", dest="hosted_node",
                           help="Proxmox node IP/hostname where the hosted guest will be created")
        parser.add_argument("--hosted-user", dest="hosted_user", default="root",
                           help="SSH user for Proxmox node (default: root)")
        parser.add_argument("--hosted-key", dest="hosted_key",
                           help="SSH key for Proxmox node (default: SSH config)")
        parser.add_argument("--memory", dest="container_memory",
                           help="Hosted guest memory (e.g. 2G, 512M)")
        parser.add_argument("--storage", dest="container_storage",
                           action="append", nargs="+", metavar="STORAGE",
                           help="Hosted guest storage spec: root POOL AMOUNT, or template POOL for LXC only; repeat as needed")
        parser.add_argument("--cores", dest="container_cores", type=int, default=1,
                           help="Hosted guest CPU cores (default: 1)")
        parser.add_argument("--base", dest="container_base", default="debian",
                           help="Base OS family for the LXC template or VM image catalog (default: debian)")
        parser.add_argument("--image", dest="vm_image", default=None,
                            help="VM cloud image override: http(s) URL to a qcow2, or a "
                                 "Proxmox storage reference like 'local:iso/foo.qcow2'. "
                                 "Only used when --machine vm. Defaults to the curated "
                                 "Debian catalog (lib/cloud_images.py).")
    else:
        parser.add_argument("--name", dest="friendly_name", default=None,
                           help="Friendly name for this configuration")
    
    if for_remote:
        parser.add_argument("--system-type", dest="system_type", 
                           choices=get_system_type_names(),
                           help="System type to setup")
        parser.add_argument("--username", default=None,
                           help="Username (defaults to current user, not used for server_proxmox)")
    
    if allow_steps or for_remote:
        parser.add_argument("--steps", dest="custom_steps", 
                           help="Space-separated list of steps to run (e.g., 'install_ruby install_node')")
    parser.add_argument("--rdp", dest="enable_rdp", 
                       action=argparse.BooleanOptionalAction, 
                       default=None if not for_remote else False,
                       help="Enable RDP/XRDP setup" + ("" if for_remote else " (default: disabled)"))
    parser.add_argument("--desktop", choices=["xfce", "i3", "cinnamon", "lxqt"], 
                       default="xfce" if for_remote else None,
                       help="Desktop environment to install (default: xfce)")
    parser.add_argument("--browser", dest="browsers", 
                       action="append",
                       choices=["brave", "firefox", "browsh", "helium", "lynx", "librewolf"], 
                       help="Web browser to install (can be used multiple times, default: librewolf for desktop setups)")
    parser.add_argument("--flatpak", dest="use_flatpak", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install desktop apps via Flatpak when available (non-containerized environments)")
    parser.add_argument("--office", dest="install_office", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install LibreOffice (desktop only)")
    
    # Package installation
    parser.add_argument("--apt-install", dest="apt_packages",
                       action="append",
                       metavar="PACKAGE",
                       help="Install package via apt (can be used multiple times)")
    parser.add_argument("--flatpak-install", dest="flatpak_packages",
                       action="append",
                       metavar="PACKAGE",
                       help="Install package via flatpak (can be used multiple times)")
    
    # Theme customization
    parser.add_argument("--dark", dest="dark_theme",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Configure desktop to use dark theme")
    
    # Development tools
    parser.add_argument("--ruby", dest="install_ruby", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install Ruby + Bundler from apt packages")
    parser.add_argument("--go", dest="install_go", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install latest Go version")
    parser.add_argument("--node", dest="install_node", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install nvm + latest Node.JS + PNPM + update NPM")
    parser.add_argument("--python", dest="install_python",
                        action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                        default=None if not for_remote else False,
                        help="Install Python tooling (python aliases and uv). For shell autocompletion, use the local completions installer script.")

    # Agent VM tooling
    parser.add_argument("--gh", dest="install_gh",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Install the GitHub CLI for agent workflows")
    parser.add_argument("--codex", dest="install_codex",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Install Codex CLI with OpenAI's official installer")
    parser.add_argument("--claude", dest="install_claude",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Install Claude Code with Anthropic's official installer")
    parser.add_argument("--opencode", dest="install_opencode",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Install OpenCode with its official installer")
    parser.add_argument("--t3code", dest="install_t3code",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Install the official T3 Code AppImage and desktop launcher (x86_64 only)")
    parser.add_argument("--agent-suite", choices=AGENT_SUITES,
                       help="Agent preset: terminal adds Codex, Claude Code, OpenCode, GitHub CLI, "
                            "and common tools; desktop also adds T3 Code; full also adds Node, "
                            "Python, and Go")
    parser.add_argument("--copy-keys", dest="copy_agent_keys",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Copy credentials for selected agent tools when available locally")
    parser.add_argument("--copy-config", dest="copy_agent_config",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Copy non-secret config for selected agent tools when available locally")
    parser.add_argument("--repo", dest="agent_repos",
                       action="append",
                       metavar="GIT_URL",
                       help="Clone a git repository locally and upload it to /home/USER/repos on the target; repeat as needed")
    
    # Deployment options
    parser.add_argument("--deploy", dest="deploy_specs",
                       action=DeploySpecAction, nargs="+", metavar="DEPLOY",
                       help="Deploy git repositories as DOMAIN_OR_PATH GIT_URL pairs (can be used multiple times)")
    
    deployment_mode_group = parser.add_mutually_exclusive_group()
    deployment_mode_group.add_argument("--deployment-lite", dest="deployment_mode", action="store_const", const="lite",
                                       help="Use uploaded repository files only (skip if not available)")
    deployment_mode_group.add_argument("--deployment-full", dest="deployment_mode", action="store_const", const="full",
                                       help="Upload a fresh repository copy and rebuild everything (force redeploy)")
    
    parser.add_argument("--full-deploy", dest="full_deploy", action="store_true",
                       help="Always rebuild deployments even if they haven't changed (default: skip unchanged deployments)")
    parser.add_argument("--deploy-latest", action=DeployLatestSpecAction, nargs=2, 
                        metavar=("DOMAIN_OR_PATH", "GIT_URL"),
                        help="Deploy latest packages and releases (bypassing age policy); requires DOMAIN_OR_PATH and GIT_URL")
    parser.add_argument("--reset-migrations", dest="reset_migrations", action="store_true",
                       help="Reset Rails database schema using db:schema:load (use when migrations were squashed or reset)")
    parser.add_argument("--ssl", dest="enable_ssl", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Enable Let's Encrypt SSL/TLS certificates for deployed domains")
    parser.add_argument("--ssl-email", dest="ssl_email",
                       help="Email address for Let's Encrypt registration (optional)")
    parser.add_argument("--cloudflare", dest="enable_cloudflare", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Preconfigure server for Cloudflare tunnel (disables public HTTP/HTTPS ports)")
    parser.add_argument("--api-subdomain", dest="api_subdomain", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Deploy Rails API as a subdomain (api.domain.com) instead of a subdirectory (domain.com/api)")
    
    parser.add_argument("--cicd", dest="enable_cicd", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install webhook-based CI/CD system for GitHub Actions")
    
    parser.add_argument("--build-server", dest="is_build_server",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Configure as a build server that deploys to app servers")
    
    parser.add_argument("--app-server", dest="is_app_server",
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true",
                       default=None if not for_remote else False,
                       help="Configure as a lightweight app server to receive deployments from build server")
    
    parser.add_argument("--deploy-target", dest="deploy_targets",
                       action="append",
                       metavar="HOST",
                       help="Target app server for deployments (can be used multiple times). Subsequent --deploy flags deploy to the last specified target")
    
    parser.add_argument("--samba", dest="enable_samba", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install and configure Samba for SMB file sharing")
    parser.add_argument("--share", dest="samba_shares", 
                       action="append", nargs=4, metavar=("ACCESS_TYPE", "SHARE_NAME", "PATH", "USERS"),
                       help="Configure one Samba directory share: access_type (read|write), share_name, absolute path, comma-separated username:password pairs or usernames that resolve via --credential (can be used multiple times)")
    parser.add_argument("--credential", dest="share_credentials",
                        action="append", nargs=2, metavar=("USERNAME", "PASSWORD"),
                        help="Save a workspace credential and let --share/--mount-smb reference the username without inline passwords (can be used multiple times)")
    
    parser.add_argument("--smbclient", dest="enable_smbclient", 
                       action=argparse.BooleanOptionalAction if not for_remote else "store_true", 
                       default=None if not for_remote else False,
                       help="Install SMB/CIFS client packages for connecting to network shares (default: enabled for pc_dev)")
    
    parser.add_argument("--mount-smb", dest="smb_mounts",
                        action="append", nargs=5, metavar=("MOUNTPOINT", "IP", "CREDENTIALS", "SHARE", "SUBDIR"),
                        help="Mount SMB share: /mnt/path, ip_address, username or username:password, share_name, /share/subdirectory (can be used multiple times). Auto-enables --smbclient")
    
    parser.add_argument("--sync", dest="sync_specs", 
                       action="append", nargs=3, metavar=("SOURCE", "DESTINATION", "INTERVAL"),
                       help="Configure directory synchronization: source_path, destination_path, interval (hourly|daily|weekly|monthly). Uses rsync with systemd timer (can be used multiple times)")
    
    parser.add_argument("--scrub", dest="scrub_specs",
                       action="append", nargs=4, metavar=("DIRECTORY", "DATABASE_PATH", "REDUNDANCY", "FREQUENCY"),
                       help="Configure data integrity checking: /path/to/directory, relative/or/absolute/path/to/.pardatabase, redundancy%%, frequency (hourly|daily|weekly|monthly). Uses par2 with systemd timer (can be used multiple times)")
    
    parser.add_argument("--notify", dest="notify_specs",
                       action="append", nargs=2, metavar=("TYPE", "TARGET"),
                       help="Configure notification target: TYPE (webhook|mailbox), TARGET (URL for webhook or email for mailbox). Sends alerts for important events (errors, warnings, successes). Can be used multiple times for multiple targets.")
    
    parser.add_argument("--antistatic-server", dest="antistatic_server",
                        metavar="[DOMAIN][:PORT]",
                        help="Deploy the antistatic lobby server behind nginx. "
                            "DOMAIN is the optional public hostname; PORT is the internal listen port "
                            f"(default: 8080). Hostless specs like :8080 listen directly without nginx. "
                             "The built-in STUN responder uses direct public UDP 3478 even when Cloudflare tunnel "
                             "support is enabled.")

    antistatic_admin_group = parser.add_mutually_exclusive_group()
    antistatic_admin_group.add_argument(
        "--antistatic-admin",
        dest="antistatic_admin",
        metavar="USERNAME",
        help="Enable the HTTPS-only antistatic-server admin interface. Resolve the password "
             "from --credential USERNAME PASSWORD or the workspace credential store.",
    )
    antistatic_admin_group.add_argument(
        "--no-antistatic-admin",
        dest="antistatic_admin",
        action="store_const",
        const="",
        help="Disable the antistatic-server admin interface and remove its remote credentials.",
    )

    parser.add_argument("--antistatic-db", dest="antistatic_db",
                       metavar="[DOMAIN][:PORT]",
                       help="Deploy the antistatic-db service behind nginx. "
                            "DOMAIN is the optional public hostname; PORT is the internal listen port "
                            "(default: 8081). Hostless specs like :8081 listen directly without nginx.")

    parser.add_argument(
        "--gogs",
        dest="gogs",
        nargs="+",
        metavar="GOGS",
        help="Deploy Gogs as a minimal self-hosted Git service. "
             "Usage: --gogs DOMAIN[:PORT] [DATA_PATH]. DOMAIN is the optional public "
             "hostname, PORT defaults to 3000, and DATA_PATH defaults to /var/lib/gogs. "
             "Hostless specs like :3000 or 3000 listen directly without nginx.",
    )
    
    restart_group = parser.add_mutually_exclusive_group()
    restart_group.add_argument("--auto-restart", dest="auto_restart",
                               action="store_true",
                               default=None if not for_remote else False,
                               help="Allow automatic restarts after updates when no users are active.")
    restart_group.add_argument("--no-auto-restart", "--no-restart", dest="auto_restart",
                               action="store_false",
                               help="Disable normal automatic restarts after updates. --no-restart is deprecated.")
    parser.add_argument("--auto-restart-force-days", dest="auto_restart_force_days",
                        type=int,
                        default=None,
                        help="Force restart after this many days of deferral. Use 0 to never force.")
    parser.add_argument("--auto-restart-grace", dest="auto_restart_grace",
                        type=int,
                        default=None,
                        help="Minutes of warning before an automatic restart starts.")
    
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without executing commands")


def create_setup_argument_parser(
    description: str,
    for_remote: bool = False,
    allow_steps: bool = False
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    add_setup_arguments(parser, for_remote=for_remote, allow_steps=allow_steps)
    return parser
