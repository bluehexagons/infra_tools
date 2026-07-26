"""Agent VM setup steps for AI coding tools and uploaded repositories."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shlex
import shutil
import urllib.parse
import urllib.request
from typing import cast

from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, run
from lib.types import JSONDict, JSONList

from .common_steps import _run_as_login_user


REMOTE_AGENT_PAYLOAD_DIR = "/opt/infra_tools/agent_payload"
REMOTE_AGENT_REPOS_DIR = "/opt/infra_tools/agent_repos"
AGENT_CODING_PACKAGES = (
    "build-essential",
    "cmake",
    "ninja-build",
    "pkg-config",
    "git-lfs",
    "ripgrep",
    "fd-find",
    "fzf",
    "jq",
    "bat",
    "tmux",
    "direnv",
    "shellcheck",
)


def _user_home(config: SetupConfig) -> str:
    return f"/home/{config.username}"


def _chown_path(config: SetupConfig, path: str) -> None:
    safe_username = shlex.quote(config.username)
    run(f"chown -R {safe_username}:{safe_username} {shlex.quote(path)}", check=False)


def install_github_cli(config: SetupConfig) -> None:
    """Install the GitHub CLI from GitHub's Debian apt repository."""
    if shutil.which("gh"):
        print("  GitHub CLI already installed")
        return

    if is_dry_run():
        print("  [DRY-RUN] Would install GitHub CLI")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq ca-certificates curl gpg", check=False)
    run("install -m 0755 -d /etc/apt/keyrings")
    run(
        "curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg "
        "-o /etc/apt/keyrings/githubcli-archive-keyring.gpg"
    )
    run("chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg")

    arch_result = run("dpkg --print-architecture", capture_output=True)
    arch = arch_result.stdout.strip() or "amd64"
    source_line = (
        f"deb [arch={arch} signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] "
        "https://cli.github.com/packages stable main\n"
    )
    with open("/etc/apt/sources.list.d/github-cli.list", "w", encoding="utf-8") as file_obj:
        file_obj.write(source_line)

    run("apt-get update -qq")
    if not install_package("GitHub CLI", "gh", "apt-get install -y -qq gh"):
        raise RuntimeError("GitHub CLI installation failed")


def _tool_available(config: SetupConfig, command: str, extra_path: str = "") -> bool:
    user_home = _user_home(config)
    path_prefix = '$HOME/.local/bin:$HOME/.opencode/bin'
    if extra_path:
        path_prefix = f"{extra_path}:{path_prefix}"
    result = _run_as_login_user(
        config.username,
        user_home,
        f'export PATH="{path_prefix}:$PATH" && command -v {shlex.quote(command)}',
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _ensure_agent_shell_path(config: SetupConfig) -> None:
    user_home = _user_home(config)
    bashrc_path = os.path.join(user_home, ".bashrc")
    marker = "# infra_tools agent tool paths"
    block = f'\n{marker}\nexport PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"\n'

    content = ""
    if os.path.exists(bashrc_path):
        with open(bashrc_path, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()

    if marker not in content:
        with open(bashrc_path, "a", encoding="utf-8") as file_obj:
            file_obj.write(block)

    _chown_path(config, bashrc_path)


def install_agent_coding_tools(config: SetupConfig) -> None:
    """Install a practical baseline of Debian coding and shell utilities."""
    if is_dry_run():
        print("  [DRY-RUN] Would install common agent coding tools")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    packages = " ".join(shlex.quote(package) for package in AGENT_CODING_PACKAGES)
    result = run(f"apt-get install -y -qq {packages}", check=False)
    if result.returncode != 0:
        raise RuntimeError("Common agent coding-tool installation failed")

    user_home = _user_home(config)
    local_bin = os.path.join(user_home, ".local", "bin")
    os.makedirs(local_bin, exist_ok=True)
    for alias, system_command in (("fd", "/usr/bin/fdfind"), ("bat", "/usr/bin/batcat")):
        destination = os.path.join(local_bin, alias)
        if os.path.exists(system_command) and not os.path.lexists(destination):
            os.symlink(system_command, destination)
    infra_tools_launcher = os.path.join(local_bin, "infra_tools")
    if not os.path.lexists(infra_tools_launcher):
        with open(infra_tools_launcher, "w", encoding="utf-8") as file_obj:
            file_obj.write(
                "#!/bin/sh\n"
                'exec python3 /opt/infra_tools/infra_tools.py "$@"\n'
            )
        os.chmod(infra_tools_launcher, 0o755)
    _run_as_login_user(
        config.username,
        user_home,
        "git lfs install --skip-repo",
        check=False,
        capture_output=True,
    )
    _chown_path(config, local_bin)
    _ensure_agent_shell_path(config)
    print("  Common agent coding tools installed")


def _install_script_tool(
    config: SetupConfig,
    *,
    command: str,
    label: str,
    installer: str,
) -> None:
    if is_dry_run():
        print(f"  [DRY-RUN] Would install {label}")
        return

    if _tool_available(config, command):
        _ensure_agent_shell_path(config)
        print(f"  {label} already installed")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    dependency_result = run(
        "apt-get install -y -qq ca-certificates curl bash",
        check=False,
    )
    if dependency_result.returncode != 0:
        raise RuntimeError(f"{label} installation dependencies failed")

    user_home = _user_home(config)
    result = _run_as_login_user(
        config.username,
        user_home,
        installer,
        check=False,
    )
    _ensure_agent_shell_path(config)

    if result.returncode != 0 or not _tool_available(config, command):
        raise RuntimeError(f"{label} installation failed")

    print(f"  {label} installed")


def install_codex(config: SetupConfig) -> None:
    """Install Codex CLI with OpenAI's official user-scoped installer."""
    _install_script_tool(
        config,
        command="codex",
        label="Codex CLI",
        installer="curl -fsSL https://chatgpt.com/codex/install.sh | sh",
    )


def install_claude(config: SetupConfig) -> None:
    """Install Claude Code with Anthropic's official native installer."""
    _install_script_tool(
        config,
        command="claude",
        label="Claude Code",
        installer="curl -fsSL https://claude.ai/install.sh | bash",
    )


def install_opencode(config: SetupConfig) -> None:
    """Install OpenCode with its official user-scoped installer."""
    _install_script_tool(
        config,
        command="opencode",
        label="OpenCode",
        installer="curl -fsSL https://opencode.ai/install | bash",
    )


def _latest_t3code_asset() -> tuple[str, str]:
    request = urllib.request.Request(
        "https://api.github.com/repos/pingdotgg/t3code/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "infra_tools-agent-vm",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = cast(JSONDict, json.load(response))

    assets = cast(JSONList, release.get("assets", []))
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("browser_download_url")
        digest = item.get("digest")
        if (
            isinstance(name, str)
            and name.endswith("-x86_64.AppImage")
            and isinstance(url, str)
            and isinstance(digest, str)
            and digest.startswith("sha256:")
            and len(digest.removeprefix("sha256:")) == 64
            and all(
                character in "0123456789abcdef"
                for character in digest.removeprefix("sha256:").lower()
            )
            and urllib.parse.urlparse(url).hostname == "github.com"
        ):
            return url, digest.removeprefix("sha256:")
    raise RuntimeError("The latest official T3 Code release has no verified x86_64 AppImage")


def _download_verified_file(url: str, expected_sha256: str, destination: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "infra_tools-agent-vm"})
    digest = hashlib.sha256()
    temporary = f"{destination}.download"
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with open(temporary, "wb") as file_obj:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    file_obj.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError("T3 Code AppImage checksum verification failed")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def install_t3code(config: SetupConfig) -> None:
    """Install T3 Code's official AppImage with a minimal desktop launcher."""
    if is_dry_run():
        print("  [DRY-RUN] Would install T3 Code AppImage")
        return
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        raise RuntimeError("T3 Code currently publishes a Linux AppImage only for x86_64")
    if _tool_available(config, "t3code"):
        print("  T3 Code already installed")
        return

    user_home = _user_home(config)
    app_dir = os.path.join(user_home, ".local", "share", "t3code")
    bin_dir = os.path.join(user_home, ".local", "bin")
    applications_dir = os.path.join(user_home, ".local", "share", "applications")
    os.makedirs(app_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(applications_dir, exist_ok=True)

    asset_url, expected_sha256 = _latest_t3code_asset()
    appimage_path = os.path.join(app_dir, "t3code.AppImage")
    _download_verified_file(asset_url, expected_sha256, appimage_path)
    os.chmod(appimage_path, 0o755)

    wrapper_path = os.path.join(bin_dir, "t3code")
    with open(wrapper_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(
            "#!/bin/sh\n"
            'export APPIMAGE_EXTRACT_AND_RUN="${APPIMAGE_EXTRACT_AND_RUN:-1}"\n'
            'exec "$HOME/.local/share/t3code/t3code.AppImage" "$@"\n'
        )
    os.chmod(wrapper_path, 0o755)

    desktop_path = os.path.join(applications_dir, "t3code.desktop")
    with open(desktop_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=T3 Code\n"
            "Comment=Agentic coding desktop\n"
            f"Exec={wrapper_path}\n"
            "Terminal=false\n"
            "Categories=Development;\n"
        )
    os.chmod(desktop_path, 0o644)
    _chown_path(config, app_dir)
    _chown_path(config, bin_dir)
    _chown_path(config, applications_dir)
    _ensure_agent_shell_path(config)
    print("  T3 Code installed")


def _payload_path(*parts: str) -> str:
    return os.path.join(REMOTE_AGENT_PAYLOAD_DIR, *parts)


def _copy_payload_directory(config: SetupConfig, source: str, destination: str, label: str) -> None:
    if not os.path.isdir(source):
        print(f"  No {label} payload found")
        return

    os.makedirs(destination, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
    _chown_path(config, destination)
    print(f"  Copied {label} config")


def _copy_secret_file(config: SetupConfig, source: str, destination: str, label: str) -> bool:
    if not os.path.isfile(source):
        print(f"  No {label} credential payload found")
        return False

    os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
    shutil.copy2(source, destination)
    os.chmod(destination, 0o600)
    _chown_path(config, destination)
    print(f"  Copied {label} credentials")
    return True


def _configure_github_git_credentials(config: SetupConfig) -> None:
    """Wire git HTTPS auth through gh for the setup user when gh auth works."""
    user_home = _user_home(config)
    result = _run_as_login_user(
        config.username,
        user_home,
        'export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH" && '
        'if gh auth status >/dev/null 2>&1; then '
        'gh auth setup-git >/dev/null; '
        'else exit 2; fi',
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        print("  Configured git to use GitHub CLI credentials")
    elif result.returncode == 2:
        print("  GitHub CLI credentials copied, but gh auth status did not pass")
    else:
        print("  Warning: failed to configure git for GitHub CLI credentials")


def copy_agent_tooling_payload(config: SetupConfig) -> None:
    """Install uploaded config and credential payloads for selected agent tools."""
    if not config.install_gh and not config.selected_agent_tools():
        print("  No selected agent tools for config or credential copy")
        return

    if is_dry_run():
        print("  [DRY-RUN] Would copy selected agent tool config and credentials")
        return

    user_home = _user_home(config)

    if config.copy_agent_config and config.install_codex:
        _copy_payload_directory(
            config,
            _payload_path("config", "codex"),
            os.path.join(user_home, ".codex"),
            "Codex",
        )

    if config.copy_agent_keys and config.install_codex:
        _copy_secret_file(
            config,
            _payload_path("secrets", "codex", "auth.json"),
            os.path.join(user_home, ".codex", "auth.json"),
            "Codex",
        )

    if config.copy_agent_config and config.install_claude:
        _copy_payload_directory(
            config,
            _payload_path("config", "claude"),
            os.path.join(user_home, ".claude"),
            "Claude Code",
        )

    if config.copy_agent_keys and config.install_claude:
        _copy_secret_file(
            config,
            _payload_path("secrets", "claude", ".credentials.json"),
            os.path.join(user_home, ".claude", ".credentials.json"),
            "Claude Code",
        )

    if config.copy_agent_config and config.install_opencode:
        _copy_payload_directory(
            config,
            _payload_path("config", "opencode"),
            os.path.join(user_home, ".config", "opencode"),
            "OpenCode",
        )

    if config.copy_agent_keys and config.install_opencode:
        _copy_secret_file(
            config,
            _payload_path("secrets", "opencode", "auth.json"),
            os.path.join(user_home, ".local", "share", "opencode", "auth.json"),
            "OpenCode",
        )

    if config.copy_agent_config and config.install_gh:
        _copy_payload_directory(
            config,
            _payload_path("config", "gh"),
            os.path.join(user_home, ".config", "gh"),
            "GitHub CLI",
        )

    if config.copy_agent_keys and config.install_gh:
        copied = _copy_secret_file(
            config,
            _payload_path("secrets", "gh", "hosts.yml"),
            os.path.join(user_home, ".config", "gh", "hosts.yml"),
            "GitHub CLI",
        )
        if copied:
            _configure_github_git_credentials(config)


def install_agent_repositories(config: SetupConfig) -> None:
    """Copy uploaded working repositories into /home/USER/repos."""
    if is_dry_run():
        print("  [DRY-RUN] Would copy uploaded repositories to the setup user's repos directory")
        return

    if not os.path.isdir(REMOTE_AGENT_REPOS_DIR):
        print("  No uploaded agent repositories found")
        return

    repos_dir = os.path.join(_user_home(config), "repos")
    os.makedirs(repos_dir, exist_ok=True)
    _chown_path(config, repos_dir)

    for repo_name in sorted(os.listdir(REMOTE_AGENT_REPOS_DIR)):
        source = os.path.join(REMOTE_AGENT_REPOS_DIR, repo_name)
        if not os.path.isdir(source):
            continue

        destination = os.path.join(repos_dir, repo_name)
        if os.path.exists(destination):
            print(f"  Skipping existing repository {destination} to avoid overwriting agent work")
            continue

        shutil.copytree(source, destination, symlinks=True)
        _chown_path(config, destination)
        print(f"  Copied {repo_name} to {destination}")
