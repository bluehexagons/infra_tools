"""Agent VM setup steps for terminal AI tools and uploaded repositories."""

from __future__ import annotations

import os
import shlex
import shutil

from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, run

from .common_steps import _run_as_login_user


REMOTE_AGENT_PAYLOAD_DIR = "/opt/infra_tools/agent_payload"
REMOTE_AGENT_REPOS_DIR = "/opt/infra_tools/agent_repos"


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


def _opencode_candidate_paths(user_home: str) -> list[str]:
    return [
        os.path.join(user_home, ".opencode", "bin", "opencode"),
        os.path.join(user_home, ".local", "bin", "opencode"),
    ]


def _opencode_available(config: SetupConfig) -> bool:
    user_home = _user_home(config)
    if any(os.path.exists(path) for path in _opencode_candidate_paths(user_home)):
        return True

    result = _run_as_login_user(
        config.username,
        user_home,
        'export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH" && command -v opencode',
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


def install_opencode(config: SetupConfig) -> None:
    """Install OpenCode into the setup user's home directory."""
    if is_dry_run():
        print("  [DRY-RUN] Would install OpenCode")
        return

    if _opencode_available(config):
        _ensure_agent_shell_path(config)
        print("  OpenCode already installed")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run("apt-get install -y -qq ca-certificates curl", check=False)

    user_home = _user_home(config)
    result = _run_as_login_user(
        config.username,
        user_home,
        "curl -fsSL https://opencode.ai/install | bash",
        check=False,
    )
    _ensure_agent_shell_path(config)

    if result.returncode != 0 or not _opencode_available(config):
        raise RuntimeError("OpenCode installation failed")

    print("  OpenCode installed")


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


def _copy_secret_file(config: SetupConfig, source: str, destination: str, label: str) -> None:
    if not os.path.isfile(source):
        print(f"  No {label} credential payload found")
        return

    os.makedirs(os.path.dirname(destination), mode=0o700, exist_ok=True)
    shutil.copy2(source, destination)
    os.chmod(destination, 0o600)
    _chown_path(config, destination)
    print(f"  Copied {label} credentials")


def copy_agent_tooling_payload(config: SetupConfig) -> None:
    """Install uploaded config and credential payloads for selected agent tools."""
    if not config.install_gh and not config.install_opencode:
        print("  No selected agent tools for config or credential copy")
        return

    if is_dry_run():
        print("  [DRY-RUN] Would copy selected agent tool config and credentials")
        return

    user_home = _user_home(config)

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
        _copy_secret_file(
            config,
            _payload_path("secrets", "gh", "hosts.yml"),
            os.path.join(user_home, ".config", "gh", "hosts.yml"),
            "GitHub CLI",
        )


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
