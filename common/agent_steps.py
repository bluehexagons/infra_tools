"""Agent VM setup steps for explicit tools and target-side repositories."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import pwd
import shlex
import shutil
import tempfile
import urllib.parse
import urllib.request
from typing import cast

from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, run
from lib.types import JSONDict, JSONList

from .common_steps import _run_as_login_user


REMOTE_AGENT_PAYLOAD_DIR = "/opt/infra_tools/agent_payload"


def _user_home(config: SetupConfig) -> str:
    try:
        return pwd.getpwnam(config.username).pw_dir
    except KeyError as exc:
        raise RuntimeError(f"Target user does not exist: {config.username}") from exc


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


def install_git_for_agent_repositories(config: SetupConfig) -> None:
    """Install only the Git client required by target-side repository setup."""
    if shutil.which("git"):
        print("  Git already installed")
        return
    if is_dry_run():
        print("  [DRY-RUN] Would install Git for agent repositories")
        return
    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    if not install_package("Git", "git", "apt-get install -y -qq git"):
        raise RuntimeError("Git installation failed")


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
        installer="curl -fsSL https://chatgpt.com/codex/install.sh | env CODEX_NON_INTERACTIVE=1 sh",
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
            return url, digest.removeprefix("sha256:").lower()
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


def _reject_symlinked_agent_destination(path: str) -> None:
    """Reject symlinks in an agent-owned destination path before writing."""
    absolute_path = os.path.abspath(path)
    current = os.path.sep
    for component in absolute_path.split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise RuntimeError(f"Refusing symlinked agent destination: {current}")

    if not os.path.isdir(absolute_path):
        return

    for root, directories, files in os.walk(absolute_path, followlinks=False):
        for name in (*directories, *files):
            candidate = os.path.join(root, name)
            if os.path.islink(candidate):
                raise RuntimeError(f"Refusing symlinked agent destination: {candidate}")


def _ensure_agent_directory(path: str, mode: int = 0o700) -> None:
    """Create a directory without accepting symlinked path components."""
    absolute_path = os.path.abspath(path)
    current = os.path.sep
    for component in absolute_path.split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current):
            if os.path.islink(current) or not os.path.isdir(current):
                raise RuntimeError(f"Refusing unsafe agent destination: {current}")
            continue
        os.mkdir(current, mode)

    _reject_symlinked_agent_destination(absolute_path)


def _copy_payload_directory(config: SetupConfig, source: str, destination: str, label: str) -> None:
    if not os.path.isdir(source):
        print(f"  No {label} payload found")
        return

    _reject_symlinked_agent_destination(destination)
    _ensure_agent_directory(destination)
    _reject_symlinked_agent_destination(destination)
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
    _reject_symlinked_agent_destination(destination)
    _chown_path(config, destination)
    print(f"  Copied {label} config")


def _copy_secret_file(config: SetupConfig, source: str, destination: str, label: str) -> bool:
    if not os.path.isfile(source):
        print(f"  No {label} credential payload found")
        return False

    destination_parent = os.path.dirname(destination)
    _reject_symlinked_agent_destination(destination_parent)
    _ensure_agent_directory(destination_parent)
    _reject_symlinked_agent_destination(destination)

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(destination, flags, 0o600)
    try:
        with open(source, "rb") as source_file, os.fdopen(file_descriptor, "wb") as destination_file:
            file_descriptor = -1
            shutil.copyfileobj(source_file, destination_file)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
    os.chmod(destination, 0o600)
    _chown_path(config, destination)
    print(f"  Copied {label} credentials")
    return True


def _configure_github_git_credentials(config: SetupConfig) -> None:
    """Wire Git HTTPS auth through the selected GitHub CLI host."""
    user_home = _user_home(config)
    result = _run_as_login_user(
        config.username,
        user_home,
        'export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH" && '
        f'if gh auth status --hostname {shlex.quote(config.git_host)} >/dev/null 2>&1; then '
        f'gh auth setup-git --hostname {shlex.quote(config.git_host)} >/dev/null; '
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


def _payload_host_entry(source: str, host: str) -> str:
    with open(source, encoding="utf-8") as file_obj:
        lines = file_obj.readlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"{host}:") or line.startswith(f"'{host}':") or line.startswith(f'"{host}":'):
            start = index
            break
    if start is None:
        raise RuntimeError(f"Uploaded GitHub credentials have no entry for {host}")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and not lines[index][0].isspace() and not lines[index].lstrip().startswith("#"):
            end = index
            break
    return "".join(lines[start:end])


def _merge_github_credentials(config: SetupConfig, source: str) -> bool:
    """Replace only the selected host entry in the target gh hosts file."""
    user_home = _user_home(config)
    destination = os.path.join(user_home, ".config", "gh", "hosts.yml")
    _reject_symlinked_agent_destination(os.path.dirname(destination))
    _ensure_agent_directory(os.path.dirname(destination))
    new_entry = _payload_host_entry(source, config.git_host)
    existing = ""
    if os.path.exists(destination):
        if os.path.islink(destination):
            raise RuntimeError(f"Refusing symlinked GitHub credentials: {destination}")
        with open(destination, encoding="utf-8") as file_obj:
            existing = file_obj.read()

    lines = existing.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.startswith(f"{config.git_host}:") or line.startswith(f"'{config.git_host}':") or line.startswith(f'"{config.git_host}":'):
            start = index
            break
    if start is None:
        merged = existing.rstrip("\n")
        if merged:
            merged += "\n"
        merged += new_entry
    else:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].strip() and not lines[index][0].isspace() and not lines[index].lstrip().startswith("#"):
                end = index
                break
        merged = "".join(lines[:start]) + new_entry + "".join(lines[end:])

    descriptor, temporary = tempfile.mkstemp(
        dir=os.path.dirname(destination),
        prefix=".hosts.yml.",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            file_obj.write(merged)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    _chown_path(config, destination)
    return True


def copy_agent_tooling_payload(config: SetupConfig) -> None:
    """Install uploaded config and credential payloads, then remove the payload."""
    if not os.path.isdir(REMOTE_AGENT_PAYLOAD_DIR):
        print("  No agent configuration payload found")
        return

    if is_dry_run():
        print("  [DRY-RUN] Would copy selected agent tool config and credentials")
        return

    user_home = _user_home(config)

    try:
        if config.install_codex:
            _copy_payload_directory(
                config,
                _payload_path("config", "codex"),
                os.path.join(user_home, ".codex"),
                "Codex",
            )

        if os.path.isfile(_payload_path("secrets", "codex", "auth.json")):
            _copy_secret_file(
                config,
                _payload_path("secrets", "codex", "auth.json"),
                os.path.join(user_home, ".codex", "auth.json"),
                "Codex",
            )

        if config.install_claude:
            _copy_payload_directory(
                config,
                _payload_path("config", "claude"),
                os.path.join(user_home, ".claude"),
                "Claude Code",
            )

        if os.path.isfile(_payload_path("secrets", "claude", ".credentials.json")):
            _copy_secret_file(
                config,
                _payload_path("secrets", "claude", ".credentials.json"),
                os.path.join(user_home, ".claude", ".credentials.json"),
                "Claude Code",
            )

        if config.install_opencode:
            _copy_payload_directory(
                config,
                _payload_path("config", "opencode"),
                os.path.join(user_home, ".config", "opencode"),
                "OpenCode",
            )

        if os.path.isfile(_payload_path("secrets", "opencode", "auth.json")):
            _copy_secret_file(
                config,
                _payload_path("secrets", "opencode", "auth.json"),
                os.path.join(user_home, ".local", "share", "opencode", "auth.json"),
                "OpenCode",
            )

        if config.install_gh:
            _copy_payload_directory(
                config,
                _payload_path("config", "gh"),
                os.path.join(user_home, ".config", "gh"),
                "GitHub CLI",
            )

        gh_credentials = _payload_path("secrets", "gh", "hosts.yml")
        if config.install_gh and os.path.isfile(gh_credentials):
            if _merge_github_credentials(config, gh_credentials):
                _configure_github_git_credentials(config)
    finally:
        if os.path.isdir(REMOTE_AGENT_PAYLOAD_DIR):
            shutil.rmtree(REMOTE_AGENT_PAYLOAD_DIR)
            print("  Removed uploaded agent configuration payload")


def clone_agent_repositories(config: SetupConfig) -> None:
    """Clone requested HTTPS repositories as the target login user."""
    if not config.agent_repos:
        return
    if is_dry_run():
        for git_url in config.agent_repos:
            print(f"  [DRY-RUN] Would clone {git_url} on the target VM")
        return

    repos_dir = os.path.join(_user_home(config), "repos")
    _reject_symlinked_agent_destination(repos_dir)
    _ensure_agent_directory(repos_dir)
    _chown_path(config, repos_dir)
    for git_url in config.agent_repos:
        repo_name = git_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        destination = os.path.join(repos_dir, repo_name)
        _reject_symlinked_agent_destination(destination)
        if os.path.lexists(destination):
            if not os.path.isdir(destination):
                raise RuntimeError(f"Repository destination is not a directory: {destination}")
            result = _run_as_login_user(
                config.username,
                _user_home(config),
                f"git -C {shlex.quote(destination)} remote get-url origin",
                check=False,
                capture_output=True,
            )
            actual_url = (result.stdout or "").strip().rstrip("/")
            if result.returncode != 0 or actual_url != git_url.rstrip("/"):
                raise RuntimeError(
                    f"Existing repository {destination} has a different origin; refusing to overwrite it"
                )
            print(f"  Repository already present: {destination}")
            continue

        result = _run_as_login_user(
            config.username,
            _user_home(config),
            f"GIT_TERMINAL_PROMPT=0 git clone -- {shlex.quote(git_url)} {shlex.quote(destination)}",
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "clone failed").strip()
            raise RuntimeError(f"Failed to clone {git_url}: {detail}")
        print(f"  Cloned {git_url} to {destination}")
