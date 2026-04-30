"""Common setup steps for all system types."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Optional

from lib.config import SetupConfig
from lib.machine_state import can_manage_time_sync
from lib.remote_utils import run, is_dry_run, is_package_installed, is_service_active, file_contains, install_package
from lib.systemd_service import cleanup_service


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
    run("apt-get update -qq")
    print("  Upgrading packages...")
    run("apt-get upgrade -y -qq")
    run("apt-get autoremove -y -qq")
    
    print("  ✓ System packages updated and upgraded")


def ensure_sudo_installed(config: SetupConfig) -> None:
    install_package("sudo", "sudo", "apt-get install -y -qq sudo")


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
    run("gem install bundler --no-document", check=False)
    if shutil.which("ruby"):
        print("  ✓ Ruby + bundler installed from apt packages")


def install_go(config: SetupConfig) -> None:
    result = run("which go", check=False)
    if result.returncode == 0:
        print("  ✓ Go already installed")
        return
    
    run("apt-get install -y -qq curl wget")
    result = run("curl -s https://go.dev/VERSION?m=text | head -1", check=False, capture_output=True)
    if result.returncode != 0 or not result.stdout.strip():
        print("  ⚠ Failed to get latest Go version, skipping")
        return
    
    go_version = result.stdout.strip()
    if not go_version.startswith("go"):
        print("  ⚠ Invalid Go version format, skipping")
        return
    
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


def install_node(config: SetupConfig) -> None:
    safe_username = shlex.quote(config.username)
    user_home = f"/home/{config.username}"
    nvm_dir = f"{user_home}/.nvm"
    safe_nvm_dir = shlex.quote(nvm_dir)
    
    if os.path.exists(nvm_dir):
        print("  ✓ nvm already installed")
        return
    
    run("apt-get install -y -qq curl")
    
    nvm_version = "v0.39.7"
    
    # Install nvm as the user, explicitly setting NVM_DIR to avoid picking up
    # any system-wide NVM_DIR (e.g. /opt/nvm) from the environment
    result = run(
        f"runuser -u {safe_username} -- bash -c "
        f"'export NVM_DIR={safe_nvm_dir} && "
        f"curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/{nvm_version}/install.sh | bash'",
        check=False
    )
    if result.returncode != 0 or not os.path.exists(os.path.join(nvm_dir, "nvm.sh")):
        print("  ✗ nvm installation failed")
        return
    
    # Install Node.js LTS
    run(f"runuser -u {safe_username} -- bash -c 'export NVM_DIR={safe_nvm_dir} && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && nvm install --lts'")
    
    # Update npm and install pnpm
    run(f"runuser -u {safe_username} -- bash -c 'export NVM_DIR={safe_nvm_dir} && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && npm install -g npm@latest'")
    run(f"runuser -u {safe_username} -- bash -c 'export NVM_DIR={safe_nvm_dir} && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && npm install -g pnpm'")
    
    # Add nvm initialization to .bashrc if not already present
    bashrc_path = f"{user_home}/.bashrc"
    nvm_init = '''
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"
'''
    
    if os.path.exists(bashrc_path):
        with open(bashrc_path, "r") as f:
            bashrc_content = f.read()
        # Check for the specific export line to avoid false positives
        if 'export NVM_DIR="$HOME/.nvm"' not in bashrc_content:
            with open(bashrc_path, "a") as f:
                f.write(nvm_init)
    else:
        # .bashrc doesn't exist - this is unusual but we'll create it with nvm config
        # Copy from skeleton first if available
        skel_bashrc = "/etc/skel/.bashrc"
        if os.path.exists(skel_bashrc):
            run(f"cp {shlex.quote(skel_bashrc)} {shlex.quote(bashrc_path)}")
            with open(bashrc_path, "a") as f:
                f.write(nvm_init)
        else:
            with open(bashrc_path, "w") as f:
                f.write(nvm_init)
    
    run(f"chown {safe_username}:{safe_username} {shlex.quote(bashrc_path)}")
    
    print("  ✓ nvm + Node.js LTS + NPM (latest) + PNPM installed for user")


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
    suspicious_patterns = ["rm -rf /", "chmod -R 777 /", "mkfs.", "dd if=", "curl | sh", "wget | sh"]
    if any(pattern in content for pattern in suspicious_patterns):
        return False
    return True


def install_or_update_uv(user_home: str, username: Optional[str] = None) -> bool:
    """Install or update uv for a user. Returns True if uv is available afterwards."""
    uv_path = os.path.join(user_home, ".local", "bin", "uv")
    safe_home = shlex.quote(user_home)
    safe_username = shlex.quote(username) if username else None

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
            if (file_mode & 0o033) != 0 or (file_mode & 0o100) == 0:
                print("  ✗ Downloaded uv installer file permissions are too broad")
                return False

            if not _validate_uv_install_script(installer_path):
                print("  ✗ Downloaded uv installer failed validation")
                return False

            if username:
                install_result = run(
                    f"runuser -u {safe_username} -- env HOME={safe_home} sh {safe_installer}",
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
        update_result = run(
            f"runuser -u {safe_username} -- env HOME={safe_home} {safe_uv_path} self update",
            check=False
        )
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


def _configure_auto_update_systemd(
    service_name: str,
    service_desc: str,
    timer_desc: str,
    script_name: str,
    schedule: str,
    check_path: str,
    check_name: str,
    user: Optional[str] = None
) -> None:
    """Helper to configure systemd service and timer for auto-updates."""
    if not os.path.exists(check_path):
        print(f"  ℹ {check_name} not installed, skipping auto-update configuration")
        return

    service_file = f"/etc/systemd/system/{service_name}.service"
    timer_file = f"/etc/systemd/system/{service_name}.timer"

    # Clean up any existing service/timer before creating new ones
    cleanup_service(service_name)

    script_path = f"/opt/infra_tools/common/service_tools/{script_name}"
    
    user_line = f"User={user}\n" if user else ""
    
    service_content = f"""[Unit]
Description={service_desc}
Documentation=man:systemd.service(5)

[Service]
Type=oneshot
{user_line}ExecStart=/usr/bin/python3 {script_path}
StandardOutput=journal
StandardError=journal
"""

    with open(service_file, "w") as f:
        f.write(service_content)

    timer_content = f"""[Unit]
Description={timer_desc}
Documentation=man:systemd.timer(5)

[Timer]
OnCalendar={schedule}
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
"""

    with open(timer_file, "w") as f:
        f.write(timer_content)

    run("systemctl daemon-reload")
    run(f"systemctl enable {service_name}.timer")
    run(f"systemctl start {service_name}.timer")

    print(f"  ✓ {check_name} auto-update configured ({schedule})")


def configure_auto_update_ruby(config: SetupConfig) -> None:
    """Configure automatic updates for global Ruby gems."""
    gem_path = shutil.which("gem") or "/usr/bin/gem"

    _configure_auto_update_systemd(
        service_name="auto-update-ruby",
        service_desc="Auto-update global Ruby gems",
        timer_desc="Auto-update Ruby gems weekly",
        script_name="auto_update_ruby.py",
        schedule="Sun *-*-* 04:00:00",
        check_path=gem_path,
        check_name="Ruby gems",
    )


def configure_auto_update_uv(config: SetupConfig) -> None:
    """Configure automatic updates for uv."""
    user_home = f"/home/{config.username}"
    uv_path = f"{user_home}/.local/bin/uv"

    _configure_auto_update_systemd(
        service_name="auto-update-uv",
        service_desc="Auto-update uv package manager",
        timer_desc="Auto-update uv weekly",
        script_name="auto_update_uv.py",
        schedule="Sun *-*-* 05:00:00",
        check_path=uv_path,
        check_name="uv",
        user=config.username
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
