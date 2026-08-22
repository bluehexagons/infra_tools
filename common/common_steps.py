"""Common setup steps for all system types."""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import tempfile
from typing import Optional

from lib.maintenance_systemd import configure_maintenance_timer
from lib.apt_sources import ensure_debian_package_sources
from lib.config import SetupConfig
from lib.machine_state import can_manage_time_sync
from lib.remote_utils import (
    file_contains,
    install_package,
    is_dry_run,
    is_package_installed,
    get_user_home,
    run,
)
from lib.update_policy import ECOSYSTEM_AUTO_UPGRADE_ENV, npm_freshness_args
from lib.validators import validate_username


NVM_VERSION = "v0.40.6"
_GO_ARCH_BY_MACHINE = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv6l": "armv6l",
    "armv7l": "armv6l",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
    "riscv64": "riscv64",
    "loongarch64": "loong64",
}
_APT_DPKG_NONINTERACTIVE_OPTIONS = (
    "-o Dpkg::Options::=--force-confdef "
    "-o Dpkg::Options::=--force-confold"
)
_USER_COMMAND_SYSTEM_PATH = (
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)
PACKAGE_UPDATE_MARKER = "/var/lib/infra_tools/state/package-update-complete"
VM_SETUP_SUDOERS_DIR = "/etc/sudoers.d"
CLI_TOOL_PACKAGES = (
    "bc",
    "btop",
    "curl",
    "file",
    "git",
    "htop",
    "jq",
    "less",
    "make",
    "neovim",
    "patch",
    "ripgrep",
    "rsync",
    "sqlite3",
    "tmux",
    "tree",
    "unzip",
    "wget",
    "xdg-utils",
    "zip",
)
DATA_ANALYSIS_PACKAGES = (
    "csvkit",
    "jupyterlab",
    "python3-matplotlib",
    "python3-numpy",
    "python3-pandas",
    "python3-scipy",
)


def _go_release_arch(machine: Optional[str] = None) -> Optional[str]:
    """Return the Go download architecture for a Linux machine name."""
    machine_name = (machine or platform.machine()).strip().lower()
    return _GO_ARCH_BY_MACHINE.get(machine_name)


def _select_go_download(
    payload: object,
    architecture: str,
    requested_version: Optional[str],
) -> tuple[str, str, str]:
    """Return (version, archive, sha256) from the official Go release feed."""
    if not isinstance(payload, list):
        raise RuntimeError("Go release feed did not return an array")
    requested_parts = None
    if requested_version:
        try:
            requested_parts = tuple(int(part) for part in requested_version.split("."))
        except ValueError as exc:
            raise RuntimeError(f"Invalid requested Go version: {requested_version}") from exc
        if len(requested_parts) != 3:
            raise RuntimeError(f"Invalid requested Go version: {requested_version}")

    candidates: list[tuple[tuple[int, int, int], str, str, str]] = []
    for release in payload:
        if not isinstance(release, dict) or not release.get("stable"):
            continue
        version = release.get("version")
        if not isinstance(version, str) or not version.startswith("go"):
            continue
        try:
            version_parts = tuple(int(part) for part in version[2:].split("."))
        except ValueError:
            continue
        if len(version_parts) != 3:
            continue
        if requested_parts and version_parts[:2] != requested_parts[:2]:
            continue
        if requested_parts and version_parts < requested_parts:
            continue
        for file_info in release.get("files", []):
            if not isinstance(file_info, dict):
                continue
            if (
                file_info.get("os") == "linux"
                and file_info.get("arch") == architecture
                and file_info.get("kind") == "archive"
                and isinstance(file_info.get("filename"), str)
                and isinstance(file_info.get("sha256"), str)
            ):
                filename = file_info["filename"]
                checksum = file_info["sha256"].lower()
                if os.path.basename(filename) != filename:
                    continue
                if len(checksum) != 64 or any(
                    character not in "0123456789abcdef" for character in checksum
                ):
                    continue
                candidates.append(
                    (version_parts, version, filename, checksum)
                )
    if not candidates:
        requested = f" for Go {requested_version}" if requested_version else ""
        raise RuntimeError(f"No supported Linux/{architecture} Go archive found{requested}")
    _parts, version, filename, checksum = max(candidates)
    return version, filename, checksum


def set_user_password(username: str, password: str) -> bool:
    process = run(
        "chpasswd",
        check=False,
        capture_output=True,
        input_data=f"{username}:{password}\n",
    )
    if process.returncode != 0:
        print(f"  Warning: Failed to set password: {process.stderr}")
        return False
    return True


def update_and_upgrade_packages(config: SetupConfig) -> None:
    check_debian_package_sources(config)
    if not config.refresh_packages and os.path.exists(PACKAGE_UPDATE_MARKER):
        print(
            "  ✓ System packages already reconciled; skipping APT update/upgrade "
            "(use --refresh-packages to force it)"
        )
        return

    print("  Updating package lists (APT may wait for another package operation)...")
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    update_result = run("apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Use-Pty=0 update -q", check=False)
    if update_result.returncode != 0:
        details = getattr(update_result, "stderr", "") or "check network connectivity and APT sources"
        raise RuntimeError(f"APT package list update failed: {str(details).strip()[:300]}")
    print("  Upgrading packages...")
    run(f"apt-get upgrade -y -qq {_APT_DPKG_NONINTERACTIVE_OPTIONS}")
    run(f"apt-get autoremove -y -qq {_APT_DPKG_NONINTERACTIVE_OPTIONS}")

    try:
        marker_parent = os.path.dirname(PACKAGE_UPDATE_MARKER)
        os.makedirs(marker_parent, mode=0o755, exist_ok=True)
        with open(PACKAGE_UPDATE_MARKER, "w", encoding="utf-8") as marker:
            marker.write("infra-tools package reconciliation complete\n")
        os.chmod(PACKAGE_UPDATE_MARKER, 0o644)
    except OSError as exc:
        raise RuntimeError(f"Could not record package reconciliation state: {exc}") from exc
    
    print("  ✓ System packages updated and upgraded")


def check_debian_package_sources(config: SetupConfig) -> None:
    """Check and repair Debian APT sources before package operations."""

    del config
    if is_dry_run():
        print("  [DRY-RUN] Would verify Debian APT sources and archive keyring")
        return
    ensure_debian_package_sources()


def ensure_sudo_installed(config: SetupConfig) -> None:
    install_package("sudo", "sudo", "apt-get install -y -qq sudo")


def configure_ipv4_preference(config: SetupConfig) -> None:
    """Prefer IPv4 over IPv6 to avoid hangs when IPv6 is present but non-functional."""
    import re
    gai_conf = "/etc/gai.conf"
    marker = "precedence ::ffff:0:0/96  100"

    if is_dry_run():
        print("  [DRY-RUN] Would configure IPv4 preference in /etc/gai.conf")
        return

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

    if is_dry_run():
        print("  [DRY-RUN] Would configure the UTF-8 locale")
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
        user_groups_message = "  ✓ User configured with sudo privileges and remoteusers group"
    else:
        user_groups_message = "  ✓ User configured with sudo privileges"

    print(user_groups_message)
    _ensure_vm_setup_user_sudoers(config)


def _ensure_vm_setup_user_sudoers(config: SetupConfig) -> None:
    """Install the VM setup user's passwordless sudo rule with safe metadata.

    Proxmox VM cloud-init needs this rule before the first remote setup run.
    Keeping the rule under an infra-tools-owned filename also lets reruns repair
    stale permissions left by older revisions without changing other sudoers
    policy files.
    """
    if config.machine_type != "vm" or config.username == "root":
        return
    if not validate_username(config.username):
        raise ValueError(f"Invalid setup username: {config.username}")
    if is_dry_run():
        print(
            "  [DRY-RUN] Would ensure VM setup sudoers drop-in has mode 0440"
        )
        return

    sudoers_path = os.path.join(
        VM_SETUP_SUDOERS_DIR,
        f"infra-tools-{config.username}",
    )
    sudoers_content = f"{config.username} ALL=(ALL) NOPASSWD:ALL\n"

    try:
        existing = os.stat(sudoers_path, follow_symlinks=False)
        if (
            stat.S_ISREG(existing.st_mode)
            and stat.S_IMODE(existing.st_mode) == 0o440
            and existing.st_uid == 0
            and existing.st_gid == 0
        ):
            with open(sudoers_path, "r", encoding="utf-8") as file_obj:
                if file_obj.read() == sudoers_content:
                    print("  ✓ VM setup sudoers already configured (0440)")
                    return
    except (FileNotFoundError, OSError):
        pass

    os.makedirs(VM_SETUP_SUDOERS_DIR, mode=0o755, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=VM_SETUP_SUDOERS_DIR,
        prefix=f".infra-tools-{config.username}-",
        text=True,
    )
    descriptor_open = True
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            descriptor_open = False
            file_obj.write(sudoers_content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.chown(temporary_path, 0, 0)
        os.chmod(temporary_path, 0o440)

        validation = run(
            f"visudo -cf {shlex.quote(temporary_path)}",
            check=False,
        )
        if validation.returncode != 0:
            raise RuntimeError(
                f"Generated VM setup sudoers file failed validation: {sudoers_path}"
            )

        os.replace(temporary_path, sudoers_path)
        os.chown(sudoers_path, 0, 0)
        os.chmod(sudoers_path, 0o440)
        print("  ✓ VM setup sudoers configured (root:root, mode 0440)")
    finally:
        if descriptor_open:
            os.close(descriptor)
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


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
    """Install the small command-line baseline shared by development profiles."""

    del config
    missing = [
        package for package in CLI_TOOL_PACKAGES if not is_package_installed(package)
    ]
    if not missing:
        print("  ✓ CLI tools already installed")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    package_args = " ".join(shlex.quote(package) for package in missing)
    result = run(f"apt-get install -y -qq {package_args}", check=False)
    remaining = [
        package for package in missing if not is_package_installed(package)
    ]
    if result.returncode != 0 or remaining:
        failed = ", ".join(remaining or missing)
        raise RuntimeError(f"CLI tool installation failed: {failed}")

    print(f"  ✓ Installed CLI tools: {', '.join(missing)}")


def install_data_analysis_tools(config: SetupConfig) -> None:
    """Install the opt-in Python data-analysis and notebook bundle."""

    del config
    missing = [
        package
        for package in DATA_ANALYSIS_PACKAGES
        if not is_package_installed(package)
    ]
    if not missing:
        print("  ✓ Data-analysis tools already installed")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    package_args = " ".join(shlex.quote(package) for package in missing)
    result = run(f"apt-get install -y -qq {package_args}", check=False)
    remaining = [
        package for package in missing if not is_package_installed(package)
    ]
    if result.returncode != 0 or remaining:
        failed = ", ".join(remaining or missing)
        raise RuntimeError(f"Data-analysis tool installation failed: {failed}")

    print(f"  ✓ Installed data-analysis tools: {', '.join(missing)}")


CONTROL_PLANE_PACKAGES = (
    "acl",
    "bash-completion",
    "bc",
    "btop",
    "ca-certificates",
    "bind9-dnsutils",
    "fd-find",
    "file",
    "findutils",
    "fzf",
    "git-lfs",
    "iproute2",
    "iputils-ping",
    "jq",
    "less",
    "lsof",
    "netcat-openbsd",
    "neovim",
    "openssh-client",
    "procps",
    "psmisc",
    "ripgrep",
    "rsync",
    "shellcheck",
    "tmux",
    "tree",
    "unzip",
    "wget",
    "zip",
)


def install_control_plane_tools(config: SetupConfig) -> None:
    """Install common Debian administrator and Linux control-plane tools."""
    if is_dry_run():
        print(
            "  [DRY-RUN] Would install control-plane tools: "
            f"{', '.join(CONTROL_PLANE_PACKAGES)}"
        )
        return

    missing = [
        package
        for package in CONTROL_PLANE_PACKAGES
        if not is_package_installed(package)
    ]
    if not missing:
        print("  ✓ Control-plane administrator tools already installed")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    package_args = " ".join(shlex.quote(package) for package in missing)
    result = run(f"apt-get install -y -qq {package_args}", check=False)
    remaining = [
        package
        for package in missing
        if not is_package_installed(package)
    ]
    if result.returncode != 0 or remaining:
        failed = ", ".join(remaining or missing)
        raise RuntimeError(f"Control-plane tool installation failed: {failed}")

    print(f"  ✓ Installed control-plane tools: {', '.join(missing)}")


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
    safe_path = shlex.quote(
        os.pathsep.join(
            (
                os.path.join(user_home, ".local", "bin"),
                os.path.join(user_home, ".opencode", "bin"),
                _USER_COMMAND_SYSTEM_PATH,
            )
        )
    )
    shell_script = f"cd {safe_home} && {command}"
    return run(
        f"runuser -u {safe_username} -- env "
        f"HOME={safe_home} USER={safe_username} LOGNAME={safe_username} "
        f"PATH={safe_path} "
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
    if is_dry_run():
        print("  [DRY-RUN] Would update the user's nvm shell initialization")
        return

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
    if is_dry_run():
        print("  [DRY-RUN] Would install Go")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq curl wget")
    requested_version = os.environ.get("INFRA_TOOLS_GO_VERSION") or None
    go_binary = "/usr/local/go/bin/go"
    if not os.path.exists(go_binary):
        found_go = shutil.which("go")
        if found_go:
            go_binary = found_go

    if os.path.exists(go_binary) and not config.refresh_packages and not requested_version:
        installed_result = run(
            f"{shlex.quote(go_binary)} version",
            check=False,
            capture_output=True,
        )
        if installed_result.returncode == 0:
            version_parts = installed_result.stdout.strip().split()
            installed_version = version_parts[2] if len(version_parts) >= 3 else "unknown"
            print(
                f"  ✓ Go already installed ({installed_version}); skipping release check "
                "(use --refresh-packages to check for updates)"
            )
            return

    go_arch = _go_release_arch()
    if go_arch is None:
        raise RuntimeError(f"Unsupported Go architecture: {platform.machine()}")
    result = run(
        "curl -fsSL 'https://go.dev/dl/?mode=json&include=all'",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Failed to retrieve the official Go release feed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Official Go release feed returned invalid JSON") from exc
    go_version, go_archive, expected_checksum = _select_go_download(
        payload,
        go_arch,
        requested_version,
    )

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
    
    download_url = f"https://go.dev/dl/{go_archive}"
    with tempfile.TemporaryDirectory(prefix="infra-tools-go-release-") as temporary_dir:
        archive_path = os.path.join(temporary_dir, go_archive)
        run(
            f"wget -q --https-only {shlex.quote(download_url)} "
            f"-O {shlex.quote(archive_path)}"
        )
        checksum_result = run(
            f"sha256sum {shlex.quote(archive_path)}",
            check=False,
            capture_output=True,
        )
        actual_checksum = (
            checksum_result.stdout.strip().split()[0]
            if checksum_result.returncode == 0
            else ""
        )
        if actual_checksum != expected_checksum:
            raise RuntimeError(f"Checksum verification failed for {go_archive}")
        run("rm -rf /usr/local/go")
        run(f"tar -C /usr/local -xzf {shlex.quote(archive_path)}")
    
    profile_d_path = "/etc/profile.d/go.sh"
    with open(profile_d_path, "w") as f:
        f.write('export PATH=$PATH:/usr/local/go/bin\n')
    run(f"chmod +x {profile_d_path}")
    
    print(f"  ✓ Go {go_version} installed")


def install_node_for_user(
    username: str,
    user_home: str,
    *,
    refresh: bool = False,
) -> None:
    """Install nvm-managed Node.js for a specific login/build user."""
    if is_dry_run():
        print("  [DRY-RUN] Would install Node.js for the setup user")
        return

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

        if not refresh:
            return
        print("  Refreshing Node.js LTS, npm, and pnpm")
        nvm_env = f"export NVM_DIR={safe_nvm_dir} && [ -s \"$NVM_DIR/nvm.sh\" ] && . \"$NVM_DIR/nvm.sh\""
        _run_as_login_user(
            username,
            user_home,
            f"{nvm_env} && nvm install --lts && nvm alias default 'lts/*'",
        )
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
        _chown_existing_paths(username, _user_tool_paths(user_home))
        print("  ✓ Node.js LTS + NPM (latest) + PNPM refreshed for user")
        return
    
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq curl")

    # Install nvm as the user, explicitly setting NVM_DIR to avoid picking up
    # any system-wide NVM_DIR (e.g. /opt/nvm) from the environment
    result = _run_as_login_user(
        username,
        user_home,
        f"export NVM_DIR={safe_nvm_dir} && "
        f"curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/{NVM_VERSION}/install.sh | bash",
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
    install_node_for_user(
        config.username,
        get_user_home(config.username),
        refresh=config.refresh_packages,
    )


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


def install_or_update_uv(
    user_home: str,
    username: Optional[str] = None,
    *,
    update: bool = True,
) -> bool:
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

            # mkstemp creates a root-only file. The validated installer must
            # be readable by the unprivileged account that executes it.
            if username:
                os.chmod(installer_path, 0o644)

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
    if not update and os.path.exists(uv_path):
        print("  ✓ uv already installed; skipping update")
        return True

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
    if is_dry_run():
        print("  [DRY-RUN] Would install Python tooling")
        return

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
    if install_or_update_uv(
        user_home=user_home,
        username=config.username,
        update=not uv_preexisting or config.refresh_packages,
    ):
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
