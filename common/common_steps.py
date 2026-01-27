"""Common setup steps for all system types."""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Optional

from lib.config import SetupConfig
from lib.machine_state import can_manage_time_sync
from lib.remote_utils import run, is_package_installed, is_service_active, file_contains, generate_password


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
    if is_package_installed("sudo"):
        print("  ✓ sudo already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq sudo")
    
    print("  ✓ sudo installed")


def configure_locale(config: SetupConfig) -> None:
    if file_contains("/etc/environment", "LANG=en_US.UTF-8"):
        print("  ✓ UTF-8 locale already configured")
        return
    
    run("apt-get install -y -qq locales")
    run("sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen")
    run("locale-gen")
    run("update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8")
    
    os.environ["LANG"] = "en_US.UTF-8"
    os.environ["LC_ALL"] = "en_US.UTF-8"
    
    with open("/etc/environment", "a+") as f:
        f.seek(0)
        existing = f.read()
        if "LANG=en_US.UTF-8" not in existing:
            f.write('LANG=en_US.UTF-8\nLC_ALL=en_US.UTF-8\n')
    
    print("  ✓ UTF-8 locale configured (en_US.UTF-8)")


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
            generated = generate_password()
            if set_user_password(config.username, generated):
                print(f"  Generated password: {generated}")
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
    
    if not is_package_installed("chrony"):
        run("apt-get install -y -qq chrony")
        print("  ✓ chrony installed")
    
    run("systemctl enable chrony", check=False)
    run("systemctl start chrony", check=False)
    
    run(f"timedatectl set-timezone {shlex.quote(tz)}", check=False)
    print(f"  ✓ Time synchronization configured (chrony, timezone: {tz})")


def install_cli_tools(config: SetupConfig) -> None:
    run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils rsync")

    print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip, rsync)")


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
    safe_username = shlex.quote(config.username)
    user_home = f"/home/{config.username}"
    rbenv_dir = f"{user_home}/.rbenv"
    
    if os.path.exists(rbenv_dir):
        print("  ✓ rbenv already installed")
        return
    
    run("apt-get install -y -qq git curl libssl-dev libreadline-dev zlib1g-dev autoconf bison build-essential libyaml-dev libncurses5-dev libffi-dev libgdbm-dev ruby ruby-dev")
    run("gem install bundler", check=False)
    
    run(f"runuser -u {safe_username} -- git clone https://github.com/rbenv/rbenv.git {shlex.quote(rbenv_dir)}")
    run(f"runuser -u {safe_username} -- git clone https://github.com/rbenv/ruby-build.git {shlex.quote(rbenv_dir)}/plugins/ruby-build")
    
    bashrc_path = f"{user_home}/.bashrc"
    rbenv_init = '''
export PATH="$HOME/.rbenv/bin:$PATH"
eval "$(rbenv init -)"
'''
    
    if not os.path.exists(bashrc_path):
        with open(bashrc_path, "w") as f:
            f.write(rbenv_init)
    else:
        with open(bashrc_path, "a") as f:
            f.write(rbenv_init)
    run(f"chown {safe_username}:{safe_username} {shlex.quote(bashrc_path)}")
    
    result = run(f"runuser -u {safe_username} -- bash -c 'export PATH=\"{rbenv_dir}/bin:$PATH\" && rbenv install -l | grep -E \"^[0-9]+\\.[0-9]+\\.[0-9]+$\" | tail -1'", check=False)
    if result.returncode == 0 and result.stdout.strip():
        latest_ruby = result.stdout.strip()
        print(f"  Installing Ruby {latest_ruby}...")
        run(f"runuser -u {safe_username} -- bash -c 'export PATH=\"{rbenv_dir}/bin:$PATH\" && rbenv install {shlex.quote(latest_ruby)}'")
        run(f"runuser -u {safe_username} -- bash -c 'export PATH=\"{rbenv_dir}/bin:$PATH\" && rbenv global {shlex.quote(latest_ruby)}'")
        run(f"runuser -u {safe_username} -- bash -c 'export PATH=\"{rbenv_dir}/bin:$PATH\" && eval \"$(rbenv init -)\" && gem install bundler'")
        print(f"  ✓ rbenv + Ruby {latest_ruby} + bundler installed")
    else:
        print("  ✓ rbenv + system Ruby + bundler installed")


def install_go(config: SetupConfig) -> None:
    result = run("which go", check=False)
    if result.returncode == 0:
        print("  ✓ Go already installed")
        return
    
    run("apt-get install -y -qq curl wget")
    result = run("curl -s https://go.dev/VERSION?m=text | head -1", check=False)
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
    nvm_dir = "/opt/nvm"
    
    if not os.path.exists(nvm_dir):
        print("  Installing nvm globally to /opt/nvm...")
        run("apt-get install -y -qq curl")
        run(f"mkdir -p {nvm_dir}")
        nvm_version = "v0.39.7"
        
        run(f"curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/{nvm_version}/install.sh | NVM_DIR={nvm_dir} bash")
        
        run(f"bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && nvm install --lts'")
        run(f"bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && npm install -g npm@latest'")
        run(f"bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && npm install -g pnpm'")
        
        run(f"chmod -R a+rX {nvm_dir}")
        
        with open("/etc/profile.d/nvm.sh", "w") as f:
            f.write(f'export NVM_DIR="{nvm_dir}"\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n')
        
        print("  ✓ nvm + Node.js LTS + NPM (latest) + PNPM installed globally")
    else:
        print("  ✓ nvm already installed in /opt/nvm")

    node_path_result = run(f"bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && which node'", check=False)
    if node_path_result.returncode == 0 and node_path_result.stdout.strip():
        node_bin = node_path_result.stdout.strip()
        node_dir = os.path.dirname(node_bin)
        
        links_created = False
        for tool in ["node", "npm", "npx", "pnpm"]:
            tool_path = os.path.join(node_dir, tool)
            link_path = f"/usr/local/bin/{tool}"
            if os.path.exists(tool_path):
                if not os.path.exists(link_path) or os.path.realpath(link_path) != os.path.realpath(tool_path):
                    run(f"ln -sf {tool_path} {link_path}")
                    links_created = True
        
        if links_created:
            print("  ✓ Node.js binaries linked to /usr/local/bin")


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

    if os.path.exists(service_file) and os.path.exists(timer_file):
        if is_service_active(f"{service_name}.timer"):
            print(f"  ✓ {check_name} auto-update already configured")
            return

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


def configure_auto_update_node(config: SetupConfig) -> None:
    """Configure automatic updates for Node.js via nvm."""
    _configure_auto_update_systemd(
        service_name="auto-update-node",
        service_desc="Auto-update Node.js to latest LTS",
        timer_desc="Auto-update Node.js weekly",
        script_name="auto_update_node.py",
        schedule="Sun *-*-* 03:00:00",
        check_path="/opt/nvm",
        check_name="Node.js"
    )


def configure_auto_update_ruby(config: SetupConfig) -> None:
    """Configure automatic updates for Ruby via rbenv."""
    user_home = f"/home/{config.username}"
    rbenv_dir = f"{user_home}/.rbenv"
    
    _configure_auto_update_systemd(
        service_name="auto-update-ruby",
        service_desc="Auto-update Ruby to latest stable version",
        timer_desc="Auto-update Ruby weekly",
        script_name="auto_update_ruby.py",
        schedule="Sun *-*-* 04:00:00",
        check_path=rbenv_dir,
        check_name="Ruby",
        user=config.username
    )


def install_mail_utils(config: SetupConfig) -> None:
    """Install mail utilities for email notifications."""
    if is_package_installed("bsd-mailx"):
        print("  ✓ Mail utilities already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq bsd-mailx")
    
    print("  ✓ Mail utilities installed")
