"""Common setup steps for all system types."""

import os
import shlex
import subprocess
from typing import Optional

from .utils import run, is_package_installed, is_service_active, file_contains, generate_password


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


def update_and_upgrade_packages(os_type: str, **_) -> None:
    print("  Updating package lists...")
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get update -qq")
    print("  Upgrading packages...")
    run("apt-get upgrade -y -qq")
    run("apt-get autoremove -y -qq")
    
    print("  ✓ System packages updated and upgraded")


def ensure_sudo_installed(os_type: str, **_) -> None:
    if is_package_installed("sudo", os_type):
        print("  ✓ sudo already installed")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get update -qq")
    run("apt-get install -y -qq sudo")
    
    print("  ✓ sudo installed")


def configure_locale(os_type: str, **_) -> None:
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


def setup_user(username: str, pw: Optional[str], os_type: str, **_) -> None:
    safe_username = shlex.quote(username)
    
    result = run(f"id {safe_username}", check=False)
    user_exists = result.returncode == 0
    
    if not user_exists:
        run(f"useradd -m -s /bin/bash {safe_username}")
        print(f"  Created new user: {username}")
        if pw:
            if set_user_password(username, pw):
                print("  Password set")
        else:
            generated = generate_password()
            if set_user_password(username, generated):
                print(f"  Generated password: {generated}")
    else:
        print(f"  User already exists: {username}")
        if pw:
            if set_user_password(username, pw):
                print("  Password updated")
    
    run(f"usermod -aG sudo {safe_username}", check=False)
    
    result = run("getent group remoteusers", check=False)
    if result.returncode == 0:
        run(f"usermod -aG remoteusers {safe_username}", check=False)
        print("  ✓ User configured with sudo privileges and remoteusers group")
    else:
        print("  ✓ User configured with sudo privileges")


def generate_ssh_key(username: str, **_) -> None:
    """Generate SSH key pair for user using default algorithm."""
    safe_username = shlex.quote(username)
    user_home = f"/home/{username}"
    ssh_dir = f"{user_home}/.ssh"
    private_key = f"{ssh_dir}/id_ed25519"
    public_key = f"{private_key}.pub"
    
    if os.path.exists(private_key):
        print(f"  ✓ SSH key already exists for {username}")
        return
    
    run(f"mkdir -p {shlex.quote(ssh_dir)}")
    run(f"chmod 700 {shlex.quote(ssh_dir)}")
    
    safe_private_key = shlex.quote(private_key)
    safe_comment = shlex.quote(f"{username}@workstation")
    run(f"runuser -u {safe_username} -- ssh-keygen -t ed25519 -f {safe_private_key} -N '' -C {safe_comment}")
    
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(ssh_dir)}")
    run(f"chmod 600 {shlex.quote(private_key)}")
    run(f"chmod 644 {shlex.quote(public_key)}", check=False)
    
    print(f"  ✓ SSH key generated for {username} (~/.ssh/id_ed25519)")


def copy_ssh_keys_to_user(username: str, **_) -> None:
    safe_username = shlex.quote(username)
    user_home = f"/home/{username}"
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
    
    print(f"  ✓ SSH keys copied to {username}")


def configure_time_sync(os_type: str, timezone: Optional[str] = None, **_) -> None:
    tz = timezone if timezone else "UTC"
    
    if not is_package_installed("systemd-timesyncd", os_type):
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        run("apt-get install -y -qq systemd-timesyncd")
    run("timedatectl set-ntp true")

    run(f"timedatectl set-timezone {shlex.quote(tz)}")
    print(f"  ✓ Time synchronization configured (NTP enabled, timezone: {tz})")


def install_cli_tools(os_type: str, **_) -> None:
    if is_package_installed("neovim", os_type):
        print("  ✓ CLI tools already installed")
        return

    run("apt-get install -y -qq neovim btop htop curl wget git tmux unzip xdg-utils")

    print("  ✓ CLI tools installed (neovim, btop, htop, curl, wget, git, tmux, unzip)")


def check_restart_required(os_type: str, **_) -> None:
    needs_restart = False
    
    if os.path.exists("/var/run/reboot-required"):
        needs_restart = True
    
    if needs_restart:
        print("  ⚠ System restart recommended (kernel/system updates)")
        print("  Run 'sudo reboot' when convenient")
    else:
        print("  ✓ No restart required")


def install_ruby(username: str, os_type: str, **_) -> None:
    safe_username = shlex.quote(username)
    user_home = f"/home/{username}"
    rbenv_dir = f"{user_home}/.rbenv"
    
    if os.path.exists(rbenv_dir):
        print("  ✓ rbenv already installed")
        return
    
    run("apt-get install -y -qq git curl libssl-dev libreadline-dev zlib1g-dev autoconf bison build-essential libyaml-dev libncurses5-dev libffi-dev libgdbm-dev")
    run(f"runuser -u {safe_username} -- git clone https://github.com/rbenv/rbenv.git {shlex.quote(rbenv_dir)}")
    run(f"runuser -u {safe_username} -- git clone https://github.com/rbenv/ruby-build.git {shlex.quote(rbenv_dir)}/plugins/ruby-build")
    
    bashrc_path = f"{user_home}/.bashrc"
    rbenv_init = '''
export PATH="$HOME/.rbenv/bin:$PATH"
eval "$(rbenv init -)"
'''
    
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
        print("  ✓ rbenv installed (Ruby installation skipped)")


def install_go(username: str, os_type: str, **_) -> None:
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


def install_node(username: str, os_type: str, **_) -> None:
    safe_username = shlex.quote(username)
    user_home = f"/home/{username}"
    nvm_dir = f"{user_home}/.nvm"
    
    if os.path.exists(nvm_dir):
        print("  ✓ nvm already installed")
        return
    
    run("apt-get install -y -qq curl")
    nvm_version = "v0.39.7"
    run(f"runuser -u {safe_username} -- bash -c 'curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/{nvm_version}/install.sh | bash'")
    run(f"runuser -u {safe_username} -- bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && nvm install --lts'")
    run(f"runuser -u {safe_username} -- bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && npm install -g npm@latest'")
    run(f"runuser -u {safe_username} -- bash -c 'export NVM_DIR=\"{nvm_dir}\" && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\" && npm install -g pnpm'")
    
    print("  ✓ nvm + Node.js LTS + NPM (latest) + PNPM installed")
