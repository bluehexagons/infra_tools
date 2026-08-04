"""Common setup steps for all system types."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Optional

from lib.apt_sources import disable_duplicate_vivaldi_source
from lib.maintenance_systemd import configure_maintenance_timer
from lib.config import SetupConfig
from lib.machine_state import can_manage_time_sync
from lib.remote_utils import run, is_dry_run, is_package_installed, is_service_active, file_contains, install_package
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV, npm_freshness_args


def set_user_password(username: str, password: str) -> bool:
    process = subprocess.run(
        ["chpasswd"],
        input=f"{username}:{password}\n",
        text=True,
        capture_output=True
    )
    if process.returncode != 0:
        print(f"  Warning: Failed to set password: {process.stderr}")
        return False
    return True


def update_and_upgrade_packages(config: SetupConfig) -> None:
    print("  Updating package lists...")
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    try:
        disabled_path = disable_duplicate_vivaldi_source()
    except (OSError, ValueError) as e:
        print(f"  ⚠ Could not clean duplicate Vivaldi APT source: {e}")
    else:
        if disabled_path:
            print(f"  ✓ Disabled duplicate Vivaldi APT source: {disabled_path}")
    run("apt-get update -qq")
    print("  Upgrading packages...")
    run("apt-get upgrade -y -qq")
    run("apt-get autoremove -y -qq")
    
    print("  ✓ System packages updated and upgraded")


def ensure_sudo_installed(config: SetupConfig) -> None:
    install_package("sudo", "sudo", "apt-get install -y -qq sudo")


def configure_ipv4_preference(config: SetupConfig) -> None:
    """Prefer IPv4 over IPv6 to avoid hangs when IPv6 is present but non-functional."""
    import re
    gai_conf = "/etc/gai.conf"
    marker = "precedence ::ffff:0:0/96  100"

    if os.path.exists(gai_conf):
        with open(gai_conf, "r") as f:
            content = f.read()
        if re.search(r"^\s*precedence\s+::ffff:0:0/96\s+100", content, re.MULTILINE):
            print("  ✓ IPv4 preference already configured")
            return
        with open(gai_conf, "a") as f:
            f.write(f"\n# Prefer IPv4 to avoid timeouts when IPv6 is non-functional\n{marker}\n")
    else:
        with open(gai_conf, "w") as f:
            f.write(f"# Prefer IPv4 to avoid timeouts when IPv6 is non-functional\n{marker}\n")

    print("  ✓ Configured IPv4 preference in /etc/gai.conf")


def configure_locale(config: SetupConfig) -> None:
    def locale_configured() -> bool:
        return file_contains("/etc/environment", "LANG=en_US.UTF-8")
    
    if locale_configured():
        print("  ✓ UTF-8 locale already configured")
        return
    
    install_package("locales", "locales", "apt-get install -y -qq locales")
    run("sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen")
    locale_gen_result = run("locale-gen", check=False)
    run("update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8", check=False)
    
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"
    
    with open("/etc/environment", "a+") as f:
        f.seek(0)
        existing = f.read()
        if "LANG=en_US.UTF-8" not in existing:
            f.write('LANG=en_US.UTF-8\nLC_ALL=en_US.UTF-8\n')
    
    if locale_gen_result.returncode == 0:
        print("  ✓ UTF-8 locale configured (en_US.UTF-8)")
    else:
        print("  ⚠ locale-gen failed; locale may not be fully configured")


def setup_user(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    
    result = run(f"id {safe_username}", check=False)
    user_exists = result.returncode == 0
    
    if not user_exists:
        run(f"useradd -m -s /bin/bash {safe_username}")
        print(f"  Created new user: {config.username}")
        if config.password:
            if set_user_password(config.username, config.password):
                print("  Password set")
        else:
            print("  No password configured; relying on SSH key authentication")
    else:
        print(f"  User already exists: {config.username}")
        if config.password:
            if set_user_password(config.username, config.password):
                print("  Password updated")
    
    run(f"usermod -aG sudo {safe_username}", check=False)
    
    result = run("getent group remoteusers", check=False)
    if result.returncode == 0:
        run(f"usermod -aG remoteusers {safe_username}", check=False)
        print("  ✓ User configured with sudo privileges and remoteusers group")
    else:
        print("  ✓ User configured with sudo privileges")


def generate_ssh_key(config: SetupConfig) -> None:
    """Generate SSH key pair for user using default algorithm."""
    safe_username = shlex.quote(config.username)
    user_home = f"/home/{config.username}"
    ssh_dir = f"{user_home}/.ssh"
    private_key = f"{ssh_dir}/id_ed25519"
    public_key = f"{private_key}.pub"
    
    if os.path.exists(private_key):
        print(f"  ✓ SSH key already exists for {config.username}")
        return
    
    run(f"mkdir -p {shlex.quote(ssh_dir)}")
    run(f"chmod 700 {shlex.quote(ssh_dir)}")
    
    safe_private_key = shlex.quote(private_key)
    safe_comment = shlex.quote(f"{config.username}@workstation")
    run(f"runuser -u {safe_username} -- ssh-keygen -t ed25519 -f {safe_private_key} -N '' -C {safe_comment}")
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(ssh_dir)}")
    run(f"chmod 600 {shlex.quote(private_key)}")
    run(f"chmod 644 {shlex.quote(public_key)}", check=False)
    
    print(f"  ✓ SSH key generated for {config.username} (~/.ssh/id_ed25519)")


def copy_ssh_keys_to_user(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    user_home = f"/home/{config.username}"
    ssh_dir = f"{user_home}/.ssh"
    authorized_keys = f"{ssh_dir}/authorized_keys"
    
    if not os.path.exists("/root/.ssh/authorized_keys"):
        print("  ℹ No SSH keys found in /root/.ssh/authorized_keys to copy")
        return
    
    run(f"mkdir -p {shlex.quote(ssh_dir)}")
    run(f"chmod 700 {shlex.quote(ssh_dir)}")
    
    run(f"cp /root/.ssh/authorized_keys {shlex.quote(authorized_keys)}")
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(ssh_dir)}")
    run(f"chmod 600 {shlex.quote(authorized_keys)}")
    
    print(f"  ✓ SSH keys copied to {config.username}")


def configure_time_sync(config: SetupConfig) -> None:
    if not can_manage_time_sync():
        print("  ✓ Skipping time sync configuration (managed by container host)")
        return
    
    tz = config.timezone if config.timezone else "UTC"
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    
    if is_package_installed("systemd-timesyncd"):
        print("  Migrating from systemd-timesyncd to chrony...")
        run("systemctl stop systemd-timesyncd", check=False)
        run("systemctl disable systemd-timesyncd", check=False)
        run("apt-get remove -y -qq systemd-timesyncd", check=False)
        print("  ✓ systemd-timesyncd removed")
    
    install_package("chrony", "chrony", "apt-get install -y -qq chrony")
    
    run("systemctl enable chrony", check=False)
    run("systemctl start chrony", check=False)
    
    run(f"timedatectl set-timezone {shlex.quote(tz)}", check=False)
    print(f"  ✓ Time synchronization configured (chrony, timezone: {tz})")


def install_cli_tools(config: SetupConfig) -> None:
    tools = ["neovim", "btop", "htop", "curl", "wget", "git", "tmux", "unzip", "xdg-utils", "rsync"]
    all_installed = all(is_package_installed(t) for t in tools)
    if all_installed:
        print("  ✓ CLI tools already installed (neovim, btop, htop, curl, wget, git, tmux, unzip, rsync)")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils rsync", check=False)
    
    if all(is_package_installed(t) for t in tools):
        print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip, rsync)")
    else:
        print("  ⚠ Some CLI tools may not have installed correctly")


def check_restart_required(config: SetupConfig) -> None:
    needs_restart = False
    
    if os.path.exists("/var/run/reboot-required"):
        needs_restart = True
    
    if needs_restart:
        print("  ⚠ System restart recommended (kernel/system updates)")
        print("  Run 'sudo reboot' when convenient")
    else:
        print("  ✓ No restart required")


def install_ruby(config: SetupConfig) -> None:
    if shutil.which("ruby") and (shutil.which("bundle") or shutil.which("bundler")):
        print("  ✓ Ruby + bundler already installed")
        return
    run("apt-get -o DPkg::Lock::Timeout=60 install -y -qq ruby ruby-dev bundler", check=False)
    if shutil.which("ruby") and (shutil.which("bundle") or shutil.which("bundler")):
        print("  ✓ Ruby + bundler installed from apt packages")
    elif shutil.which("ruby"):
        print("  ⚠ Ruby installed, but bundled apt package was unavailable")


def _run_as_login_user(
    username: str,
    user_home: str,
    command: str,
    *,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a shell command as a login user's home-scoped tool environment."""
    safe_username = shlex.quote(username)
    safe_home = shlex.quote(user_home)
    shell_script = f"cd {safe_home} && {command}"
    return run(
        f"runuser -u {safe_username} -- env "
        f"HOME={safe_home} USER={safe_username} LOGNAME={safe_username} "
        f"bash -lc {shlex.quote(shell_script)}",
        check=check,
        capture_output=capture_output,
    )


def _chown_existing_paths(username: str, paths: list[str]) -> None:
    """Ensure existing user-tool paths belong to the target login user."""
    safe_username = shlex.quote(username)
    existing_paths = [path for path in paths if os.path.exists(path)]
    for path in existing_paths:
        run(f"chown -R {safe_username}:{safe_username} {shlex.quote(path)}", check=False)


def _user_tool_paths(user_home: str) -> list[str]:
    """Return per-user tool paths that should never be root-owned."""
    return [
        os.path.join(user_home, ".nvm"),
        os.path.join(user_home, ".npm"),
        os.path.join(user_home, ".cache"),
        os.path.join(user_home, ".config"),
        os.path.join(user_home, ".local"),
    ]


def _ensure_nvm_shell_init(username: str, user_home: str) -> None:
    """Add nvm initialization to the user's .bashrc when missing."""
    bashrc_path = f"{user_home}/.bashrc"
    nvm_init = '''
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"
'''

    if os.path.exists(bashrc_path):
        with open(bashrc_path, "r") as f:
            bashrc_content = f.read()
        if 'export NVM_DIR="$HOME/.nvm"' not in bashrc_content:
            with open(bashrc_path, "a") as f:
                f.write(nvm_init)
    else:
        skel_bashrc = "/etc/skel/.bashrc"
        if os.path.exists(skel_bashrc):
            run(f"cp {shlex.quote(skel_bashrc)} {shlex.quote(bashrc_path)}")
            with open(bashrc_path, "a") as f:
                f.write(nvm_init)
        else:
            with open(bashrc_path, "w") as f:
                f.write(nvm_init)

    run(f"chown {shlex.quote(username)}:{shlex.quote(username)} {shlex.quote(bashrc_path)}")


def install_go(config: SetupConfig) -> None:
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq curl wget")
    result = run("curl -s https://go.dev/VERSION?m=text | head -1", check=False, capture_output=True)
    if result.returncode != 0 or not result.stdout.strip():
        print("  ⚠ Failed to get latest Go version, skipping")
        return
    
    go_version = result.stdout.strip()
    if not go_version.startswith("go"):
        print("  ⚠ Invalid Go version format, skipping")
        return

    go_binary = "/usr/local/go/bin/go"
    if not os.path.exists(go_binary):
        found_go = shutil.which("go")
        if found_go:
            go_binary = found_go

    if os.path.exists(go_binary):
        installed_result = run(f"{shlex.quote(go_binary)} version", check=False, capture_output=True)
        if installed_result.returncode == 0:
            version_parts = installed_result.stdout.strip().split()
            installed_version = version_parts[2] if len(version_parts) >= 3 else "unknown"
            if installed_version == go_version:
                print(f"  ✓ Go already up to date ({go_version})")
                return
            print(f"  Updating Go from {installed_version} to {go_version}...")
        else:
            print("  ⚠ Existing Go binary could not report a version; reinstalling")
    
    go_archive = f"{go_version}.linux-amd64.tar.gz"
    run(f"wget -q https://go.dev/dl/{go_archive} -O /tmp/{go_archive}")
    run("rm -rf /usr/local/go")
    run(f"tar -C /usr/local -xzf /tmp/{go_archive}")
    run(f"rm /tmp/{go_archive}")
    
    profile_d_path = "/etc/profile.d/go.sh"
    with open(profile_d_path, "w") as f:
        f.write('export PATH=$PATH:/usr/local/go/bin\n')
    run(f"chmod +x {profile_d_path}")
    
    print(f"  ✓ Go {go_version} installed")


def install_node_for_user(username: str, user_home: str) -> None:
    """Install nvm-managed Node.js for a specific login/build user."""
    nvm_dir = f"{user_home}/.nvm"
    safe_nvm_dir = shlex.quote(nvm_dir)
    nvm_sh = os.path.join(nvm_dir, "nvm.sh")

    _chown_existing_paths(username, _user_tool_paths(user_home))
    
    if os.path.exists(nvm_sh):
        _ensure_nvm_shell_init(username, user_home)
        verify_result = _run_as_login_user(
            username,
            user_home,
            f"export NVM_DIR={safe_nvm_dir} && "
            '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" && nvm --version',
            check=False,
        )
        _chown_existing_paths(username, _user_tool_paths(user_home))
        if verify_result.returncode == 0:
            print("  ✓ nvm already installed")
        else:
            print("  ⚠ nvm is installed but could not be loaded for user")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq curl")

    nvm_version = "v0.39.7"
    
    # Install nvm as the user, explicitly setting NVM_DIR to avoid picking up
    # any system-wide NVM_DIR (e.g. /opt/nvm) from the environment
    result = _run_as_login_user(
        username,
        user_home,
        f"export NVM_DIR={safe_nvm_dir} && "
        f"curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/{nvm_version}/install.sh | bash",
        check=False
    )
    _chown_existing_paths(username, _user_tool_paths(user_home))
    if result.returncode != 0 or not os.path.exists(nvm_sh):
        print("  ✗ nvm installation failed")
        return
    
    # Install Node.js LTS
    nvm_env = f"export NVM_DIR={safe_nvm_dir} && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\""
    _run_as_login_user(
        username,
        user_home,
        f"{nvm_env} && nvm install --lts && nvm alias default 'lts/*'",
    )
    
    # Update npm and install pnpm
    npm_freshness = shlex.join(npm_freshness_args())
    npm_freshness_suffix = f" {npm_freshness}" if npm_freshness else ""
    _run_as_login_user(
        username,
        user_home,
        f"{nvm_env} && npm install -g npm@latest{npm_freshness_suffix}",
    )
    _run_as_login_user(
        username,
        user_home,
        f"{nvm_env} && npm install -g pnpm{npm_freshness_suffix}",
    )
    
    _ensure_nvm_shell_init(username, user_home)
    _chown_existing_paths(username, _user_tool_paths(user_home))
    
    print("  ✓ nvm + Node.js LTS + NPM (latest) + PNPM installed for user")


def install_node(config: SetupConfig) -> None:
    install_node_for_user(config.username, f"/home/{config.username}")


def _validate_uv_install_script(script_path: str) -> bool:
    """Basic validation for uv installer script content before execution."""
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False

    stripped_content = content.lstrip()
    if not stripped_content.startswith("#!/bin/sh") and not stripped_content.startswith("#!/usr/bin/env sh"):
        return False
    if "astral.sh/uv" not in content and "github.com/astral-sh/uv" not in content:
        return False
    if "uv" not in content:
        return False
    suspicious_patterns = ["rm -rf /", "chmod -R 777 /", "mkfs.", "dd if="]
    if any(pattern in content for pattern in suspicious_patterns):
        return False
    return True


def install_or_update_uv(user_home: str, username: Optional[str] = None) -> bool:
    """Install or update uv for a user. Returns True if uv is available afterwards."""
    uv_path = os.path.join(user_home, ".local", "bin", "uv")
    safe_home = shlex.quote(user_home)
    if username:
        _chown_existing_paths(username, _user_tool_paths(user_home))

    if is_dry_run():
        print("  [DRY-RUN] Skipping uv install/update")
        return True

    if not os.path.exists(uv_path):
        fd, installer_path = tempfile.mkstemp(prefix="infra_tools_uv_install_", suffix=".sh")
        os.close(fd)
        safe_installer = shlex.quote(installer_path)

        try:
            download_result = run(
                f"curl -fsSL --proto '=https' --tlsv1.2 https://astral.sh/uv/install.sh -o {safe_installer}",
                check=False
            )
            if download_result.returncode != 0:
                return False

            file_mode = os.stat(installer_path).st_mode & 0o777
            if (file_mode & 0o033) != 0:
                print("  ✗ Downloaded uv installer file permissions are too broad")
                return False

            if not _validate_uv_install_script(installer_path):
                print("  ✗ Downloaded uv installer failed validation")
                return False

            if username:
                install_result = _run_as_login_user(
                    username,
                    user_home,
                    f"sh {safe_installer}",
                    check=False
                )
            else:
                install_result = run(f"env HOME={safe_home} sh {safe_installer}", check=False)

            if install_result.returncode != 0 or not os.path.exists(uv_path):
                return False
        finally:
            try:
                os.unlink(installer_path)
            except OSError:
                pass

    safe_uv_path = shlex.quote(uv_path)
    if username:
        update_result = _run_as_login_user(
            username,
            user_home,
            f"{safe_uv_path} self update",
            check=False
        )
        _chown_existing_paths(username, _user_tool_paths(user_home))
    else:
        update_result = run(f"env HOME={safe_home} {safe_uv_path} self update", check=False)

    if update_result.returncode == 0:
        print("  ✓ uv updated")
    else:
        print("  ⚠ uv update failed")

    return os.path.exists(uv_path)


def install_python(config: SetupConfig) -> None:
    """Install Python tooling (aliases and uv)."""
    user_home = f"/home/{config.username}"

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq python3 python3-venv curl")

    python3_path = shutil.which("python3")
    python_path = shutil.which("python")

    if python3_path and not python_path:
        run(f"ln -sfn {shlex.quote(python3_path)} /usr/local/bin/python")
        print("  ✓ Added python alias to python3")
    elif python_path:
        print("  ✓ python command already available")

    if python3_path:
        print("  ✓ python3 command already available")
    else:
        raise RuntimeError("python3 command unavailable after package installation")

    uv_preexisting = os.path.exists(f"{user_home}/.local/bin/uv")
    if install_or_update_uv(user_home=user_home, username=config.username):
        if uv_preexisting:
            print("  ✓ uv already installed")
        else:
            print("  ✓ uv installed")
    else:
        raise RuntimeError("uv installation failed")

    print("  ℹ Remote systems skip shell autocompletion setup")


def configure_auto_update_ruby(config: SetupConfig) -> None:
    """Configure automatic updates for global Ruby gems."""
    gem_path = shutil.which("gem") or "/usr/bin/gem"

    configure_maintenance_timer(
        service_name="auto-update-ruby",
        service_desc="Auto-update global Ruby gems",
        timer_desc="Auto-update Ruby gems weekly",
        script_path="/opt/infra_tools/common/service_tools/auto_update_ruby.py",
        schedule="Sun *-*-* 04:00:00",
        check_path=gem_path,
        check_name="Ruby gems",
        environment={ECOSYSTEM_AUTO_UPGRADE_ENV: "0"},
        purpose="auto-update",
    )


def configure_auto_update_uv(config: SetupConfig) -> None:
    """Configure automatic updates for uv."""
    user_home = f"/home/{config.username}"
    uv_path = f"{user_home}/.local/bin/uv"

    configure_maintenance_timer(
        service_name="auto-update-uv",
        service_desc="Auto-update uv package manager",
        timer_desc="Auto-update uv weekly",
        script_path="/opt/infra_tools/common/service_tools/auto_update_uv.py",
        schedule="Sun *-*-* 05:00:00",
        check_path=uv_path,
        check_name="uv",
        user=config.username,
        environment={ECOSYSTEM_AUTO_UPGRADE_ENV: "0"},
        purpose="auto-update",
    )


def configure_auto_update_gogs(config: SetupConfig) -> None:
    """Configure automatic updates for Gogs."""
    configure_maintenance_timer(
        service_name="auto-update-gogs",
        service_desc="Auto-update Gogs service",
        timer_desc="Auto-update Gogs weekly",
        script_path="/opt/infra_tools/common/service_tools/auto_update_gogs.py",
        schedule="Sun *-*-* 05:30:00",
        check_path="/usr/local/bin/gogs",
        check_name="Gogs",
        purpose="auto-update",
    )


def install_mail_utils(config: SetupConfig) -> None:
    """Install mail utilities for email notifications."""
    # Only install if mailbox notifications are configured
    if not config.notify_specs:
        return
    
    has_mailbox = any(spec[0] == 'mailbox' for spec in config.notify_specs)
    if not has_mailbox:
        print("  ℹ No mailbox notifications configured, skipping mail utilities")
        return
    
    if is_package_installed("bsd-mailx"):
        print("  ✓ Mail utilities already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq bsd-mailx")
    
    print("  ✓ Mail utilities installed")


def install_apt_packages(config: SetupConfig) -> None:
    """Install additional packages via apt."""
    if not config.apt_packages:
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    print("  Installing custom apt packages...")
    for package in config.apt_packages:
        if is_package_installed(package):
            print(f"  ✓ {package} already installed")
        else:
            print(f"  Installing {package}...")
            run(f"apt-get install -y -qq {shlex.quote(package)}", check=False)
            if is_package_installed(package):
                print(f"  ✓ {package} installed")
            else:
                print(f"  ⚠ Failed to install {package}")


def install_flatpak_packages(config: SetupConfig) -> None:
    """Install additional packages via flatpak."""
    if not config.flatpak_packages:
        return
    
    from lib.machine_state import is_container
    from desktop.apps_steps import is_flatpak_installed, install_flatpak_if_needed, is_flatpak_app_installed
    
    # In containers, flatpak often doesn't work
    if is_container():
        print("  ⚠ Container detected: skipping flatpak package installation")
        return
    
    # Ensure flatpak is installed
    install_flatpak_if_needed()
    
    if not is_flatpak_installed():
        print("  ⚠ Flatpak not available, skipping flatpak package installation")
        return
    
    print("  Installing custom flatpak packages...")
    FLATPAK_REMOTE = "flathub"
    
    for package in config.flatpak_packages:
        if is_flatpak_app_installed(package):
            print(f"  ✓ {package} already installed")
        else:
            print(f"  Installing {package}...")
            run(f"flatpak install -y {FLATPAK_REMOTE} {shlex.quote(package)}", check=False)
            # Verify installation
            if is_flatpak_app_installed(package):
                print(f"  ✓ {package} installed")
            else:
                print(f"  ⚠ Failed to install {package}")
