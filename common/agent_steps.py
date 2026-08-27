"""Agent VM setup steps for explicit tools and target-side repositories."""

from __future__ import annotations

import json
import os
import pwd
import shlex
import shutil
import tempfile

from lib.agent_credentials import codex_auth_warning, inspect_codex_auth_file
from lib.config import SetupConfig
from lib.remote_utils import install_package, is_dry_run, run
from lib.validation import (
    validate_filesystem_path,
    validate_git_author_email,
    validate_git_author_name,
)
from lib.validators import validate_github_login

from .common_steps import _ensure_user_tool_shell_environment, _run_as_login_user


REMOTE_AGENT_PAYLOAD_DIR = "/opt/infra_tools/agent_payload"
AGENT_CLI_SOURCE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "infra_tools.py")
)
_AGENT_CLI_MARKER = "# Managed by infra_tools agent setup"
_GIT_IDENTITY_PAYLOAD_PATH = os.path.join("config", "git", "identity.json")
_MAX_GIT_IDENTITY_PAYLOAD_BYTES = 16 * 1024


def _user_home(config: SetupConfig) -> str:
    try:
        return pwd.getpwnam(config.username).pw_dir
    except KeyError as exc:
        raise RuntimeError(f"Target user does not exist: {config.username}") from exc


def _chown_path(config: SetupConfig, path: str) -> None:
    try:
        account = pwd.getpwnam(config.username)
    except KeyError as exc:
        raise RuntimeError(f"Target user does not exist: {config.username}") from exc

    result = run(
        ["chown", "-R", f"{account.pw_uid}:{account.pw_gid}", path],
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ownership change failed").strip()
        raise RuntimeError(f"Could not set ownership for {path}: {detail}")


def _chown_user_directory_chain(
    config: SetupConfig,
    user_home: str,
    path: str,
) -> None:
    """Make every directory from ``user_home`` to ``path`` user-traversable.

    Payload setup runs as root and may create a private directory hierarchy
    before copying a single credential file. Chown only the directory entries,
    not unrelated contents in an existing user configuration tree.
    """

    try:
        account = pwd.getpwnam(config.username)
    except KeyError as exc:
        raise RuntimeError(f"Target user does not exist: {config.username}") from exc

    absolute_home = os.path.abspath(user_home)
    absolute_path = os.path.abspath(path)
    try:
        inside_home = os.path.commonpath((absolute_home, absolute_path)) == absolute_home
    except ValueError:
        inside_home = False
    if not inside_home:
        raise RuntimeError(f"Agent directory is outside the target user home: {path}")

    current = absolute_home
    relative_path = os.path.relpath(absolute_path, absolute_home)
    if relative_path == ".":
        return
    for component in relative_path.split(os.path.sep):
        current = os.path.join(current, component)
        if os.path.islink(current) or not os.path.isdir(current):
            raise RuntimeError(f"Refusing unsafe agent destination: {current}")
        result = run(
            ["chown", f"{account.pw_uid}:{account.pw_gid}", current],
            capture_output=True,
        )
        if result.returncode != 0:
            detail = (
                result.stderr or result.stdout or "ownership change failed"
            ).strip()
            raise RuntimeError(f"Could not set ownership for {current}: {detail}")


def install_agent_cli_launcher(config: SetupConfig) -> None:
    """Install a target-user launcher for agent diagnostics and maintenance."""
    if is_dry_run():
        print("  [DRY-RUN] Would install the agent VM management command")
        return

    validate_filesystem_path(AGENT_CLI_SOURCE, must_exist=True)
    if os.path.islink(AGENT_CLI_SOURCE) or not os.path.isfile(AGENT_CLI_SOURCE):
        raise RuntimeError(
            f"Agent management source is not a regular file: {AGENT_CLI_SOURCE}"
        )

    user_home = _user_home(config)
    bin_dir = os.path.join(user_home, ".local", "bin")
    launcher_path = os.path.join(bin_dir, "infra-tools")
    _reject_symlinked_agent_destination(launcher_path)
    _prepare_agent_local_bin(config, user_home)

    content = (
        "#!/bin/sh\n"
        f"{_AGENT_CLI_MARKER}\n"
        f"exec /usr/bin/python3 {shlex.quote(AGENT_CLI_SOURCE)} \"$@\"\n"
    )
    if os.path.lexists(launcher_path):
        if not os.path.isfile(launcher_path):
            raise RuntimeError(f"Refusing unsafe agent launcher: {launcher_path}")
        try:
            with open(launcher_path, encoding="utf-8") as file_obj:
                existing = file_obj.read()
        except OSError as exc:
            raise RuntimeError(
                f"Could not inspect agent launcher: {launcher_path}"
            ) from exc
        if _AGENT_CLI_MARKER not in existing:
            if not os.access(launcher_path, os.X_OK):
                raise RuntimeError(
                    f"Existing unmanaged agent launcher is not executable: {launcher_path}"
                )
            _ensure_agent_shell_path(config)
            print(f"  Existing infra-tools launcher retained: {launcher_path}")
            return
        if existing == content:
            os.chmod(launcher_path, 0o755)
            _chown_path(config, launcher_path)
            _ensure_agent_shell_path(config)
            print(f"  Agent VM management command already installed: {launcher_path}")
            return

    descriptor, temporary = tempfile.mkstemp(dir=bin_dir, prefix=".infra-tools-")
    try:
        os.fchmod(descriptor, 0o755)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            descriptor = -1
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, launcher_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if os.path.exists(temporary):
            os.unlink(temporary)

    _chown_path(config, launcher_path)
    _ensure_agent_shell_path(config)
    print(f"  Installed agent VM management command: {launcher_path}")


def install_github_cli(config: SetupConfig) -> None:
    """Install the GitHub CLI from GitHub's Debian apt repository."""
    if shutil.which("gh"):
        print("  GitHub CLI already installed")
        return

    if is_dry_run():
        print("  [DRY-RUN] Would install GitHub CLI")
        return

    os.environ["DEBIAN_FRONTEND"] = "noninteractive"
    run(["apt-get", "install", "-y", "-qq", "ca-certificates", "curl", "gpg"])
    run("install -m 0755 -d /etc/apt/keyrings")
    run(
        "curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg "
        "-o /etc/apt/keyrings/githubcli-archive-keyring.gpg"
    )
    run(["chmod", "go+r", "/etc/apt/keyrings/githubcli-archive-keyring.gpg"])

    arch_result = run("dpkg --print-architecture", capture_output=True)
    arch = arch_result.stdout.strip() or "amd64"
    source_line = (
        f"deb [arch={arch} signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] "
        "https://cli.github.com/packages stable main\n"
    )
    with open("/etc/apt/sources.list.d/github-cli.list", "w", encoding="utf-8") as file_obj:
        file_obj.write(source_line)

    run(["apt-get", "update", "-qq"])
    if not install_package("GitHub CLI", "gh", ["apt-get", "install", "-y", "-qq", "gh"]):
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
    if not install_package("Git", "git", ["apt-get", "install", "-y", "-qq", "git"]):
        raise RuntimeError("Git installation failed")


def install_git_lfs_for_agent_repositories(config: SetupConfig) -> None:
    """Install Git LFS and initialize it for the target login user."""
    if is_dry_run():
        print("  [DRY-RUN] Would install and initialize Git LFS")
        return

    if not shutil.which("git-lfs"):
        os.environ["DEBIAN_FRONTEND"] = "noninteractive"
        if not install_package("Git LFS", "git-lfs", ["apt-get", "install", "-y", "-qq", "git-lfs"]):
            raise RuntimeError("Git LFS installation failed")

    result = _run_as_login_user(
        config.username,
        _user_home(config),
        "git lfs install",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "initialization failed").strip()
        raise RuntimeError(f"Git LFS user initialization failed: {detail}")

    verification = _run_as_login_user(
        config.username,
        _user_home(config),
        "git lfs version",
        check=False,
        capture_output=True,
    )
    if verification.returncode != 0:
        raise RuntimeError("Git LFS installation could not be verified")
    print("  Git LFS installed and initialized")


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
    _ensure_user_tool_shell_environment(config.username, user_home)


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
    run(["apt-get", "install", "-y", "-qq", "ca-certificates", "curl", "bash"])

    user_home = _user_home(config)
    _prepare_agent_local_bin(config, user_home)
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


def _payload_path(*parts: str) -> str:
    return os.path.join(REMOTE_AGENT_PAYLOAD_DIR, *parts)


def _reject_symlinked_agent_destination(path: str) -> None:
    """Reject symlinked path components in an agent destination before writing.

    Do not recursively inspect an existing agent directory. Codex and other
    tools may keep legitimate runtime symlinks in temporary or cache trees
    beneath their configuration directories; only the path being written and
    its ancestors need to be protected here.
    """
    absolute_path = os.path.abspath(path)
    current = os.path.sep
    for component in absolute_path.split(os.path.sep):
        if not component:
            continue
        current = os.path.join(current, component)
        if os.path.lexists(current) and os.path.islink(current):
            raise RuntimeError(f"Refusing symlinked agent destination: {current}")


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


def _prepare_agent_local_bin(config: SetupConfig, user_home: str) -> str:
    """Create a writable target-user ``~/.local/bin`` directory.

    Setup runs as root, while vendor agent installers run as the target user.
    Repair the complete user-scoped ``.local`` tree so earlier root-created
    directories cannot block an installer's atomic link or file replacement.
    """

    local_dir = os.path.join(user_home, ".local")
    bin_dir = os.path.join(local_dir, "bin")
    _ensure_agent_directory(bin_dir, mode=0o755)
    _chown_path(config, local_dir)
    return bin_dir


def _validate_agent_payload_tree(source: str, destination: str) -> None:
    """Validate only destination paths represented by a payload tree."""
    try:
        entries = list(os.scandir(source))
    except OSError as exc:
        raise RuntimeError(f"Could not inspect agent payload: {source}") from exc

    for entry in entries:
        source_entry = entry.path
        destination_entry = os.path.join(destination, entry.name)
        if entry.is_symlink():
            raise RuntimeError(f"Refusing symlinked agent payload: {source_entry}")
        _reject_symlinked_agent_destination(destination_entry)
        if entry.is_dir(follow_symlinks=False):
            _validate_agent_payload_tree(source_entry, destination_entry)
        elif not entry.is_file(follow_symlinks=False):
            raise RuntimeError(f"Refusing unsupported agent payload entry: {source_entry}")


def _copy_payload_directory(config: SetupConfig, source: str, destination: str, label: str) -> None:
    if not os.path.isdir(source):
        print(f"  No {label} payload found")
        return
    if os.path.islink(source):
        raise RuntimeError(f"Refusing symlinked agent payload: {source}")

    _reject_symlinked_agent_destination(destination)
    _ensure_agent_directory(destination)
    _validate_agent_payload_tree(source, destination)
    _reject_symlinked_agent_destination(destination)
    _chown_user_directory_chain(config, _user_home(config), destination)
    shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
    _reject_symlinked_agent_destination(destination)
    _chown_path(config, destination)
    print(f"  Copied {label} config")


def _copy_secret_file(
    config: SetupConfig,
    source: str,
    destination: str,
    label: str,
    *,
    credential_tool: str | None = None,
) -> bool:
    """Seed a missing credential without replacing target-maintained auth state."""

    if not os.path.isfile(source):
        print(f"  No {label} credential payload found")
        return False

    destination_parent = os.path.dirname(destination)
    _reject_symlinked_agent_destination(destination_parent)
    _ensure_agent_directory(destination_parent)
    _reject_symlinked_agent_destination(destination)
    _chown_user_directory_chain(config, _user_home(config), destination_parent)
    if os.path.lexists(destination):
        if os.path.islink(destination) or not os.path.isfile(destination):
            raise RuntimeError(f"Refusing unsafe agent credential: {destination}")
        os.chmod(destination, 0o600)
        _chown_path(config, destination)
        if credential_tool == "codex":
            warning = codex_auth_warning(inspect_codex_auth_file(destination))
            if warning:
                print(f"  Warning: existing target: {warning}")
        print(
            f"  Existing {label} credentials retained; setup seeds missing "
            "credentials only"
        )
        return False

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
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
    print(f"  Seeded {label} credentials")
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
        print("  GitHub CLI credentials are present, but gh auth status did not pass")
    else:
        print("  Warning: failed to configure git for GitHub CLI credentials")


def _git_identity_payload() -> dict[str, str]:
    """Load the validated controller identity without accepting Git config."""

    source = _payload_path(*_GIT_IDENTITY_PAYLOAD_PATH.split(os.path.sep))
    if not os.path.exists(source):
        return {}
    validate_filesystem_path(source, must_exist=True)
    if (
        os.path.islink(source)
        or not os.path.isfile(source)
        or os.path.getsize(source) > _MAX_GIT_IDENTITY_PAYLOAD_BYTES
    ):
        raise RuntimeError(f"Refusing unsafe Git identity payload: {source}")
    try:
        with open(source, encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except (OSError, ValueError) as exc:
        raise RuntimeError("Could not read the Git identity payload") from exc
    if not isinstance(payload, dict) or not payload or not set(payload).issubset(
        {"name", "email"}
    ):
        raise RuntimeError("Git identity payload has invalid fields")

    identity: dict[str, str] = {}
    try:
        if "name" in payload:
            identity["name"] = validate_git_author_name(payload["name"])
        if "email" in payload:
            identity["email"] = validate_git_author_email(payload["email"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Git identity payload has invalid values") from exc
    return identity


def _configured_git_identity_value(config: SetupConfig, key: str) -> str | None:
    """Read an effective target-user Git identity value from the home directory."""

    result = _run_as_login_user(
        config.username,
        _user_home(config),
        f"git config --get {shlex.quote(key)}",
        check=False,
        capture_output=True,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git config failed").strip()
        raise RuntimeError(f"Could not inspect target Git identity: {detail}")
    value = (result.stdout or "").rstrip("\r\n")
    return value or None


def _github_git_identity(config: SetupConfig) -> dict[str, str]:
    """Derive a commit identity from the authenticated GitHub account."""

    result = _run_as_login_user(
        config.username,
        _user_home(config),
        'export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH" && '
        f"gh api user --hostname {shlex.quote(config.git_host)}",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "GitHub API request failed").strip()
        raise RuntimeError(
            "Git credentials were copied, but a Git author identity could not be "
            f"resolved: {detail}"
        )
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("GitHub returned invalid account identity data") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned invalid account identity data")

    login = payload.get("login")
    account_id = payload.get("id")
    if not isinstance(login, str) or not validate_github_login(login):
        raise RuntimeError("GitHub did not return a valid account login")

    name = payload.get("name")
    try:
        validated_name = validate_git_author_name(name)
    except (TypeError, ValueError):
        validated_name = validate_git_author_name(login)

    email = payload.get("email")
    try:
        validated_email = validate_git_author_email(email)
    except (TypeError, ValueError):
        if (
            not isinstance(account_id, int)
            or isinstance(account_id, bool)
            or account_id <= 0
        ):
            raise RuntimeError(
                "GitHub did not return an email address or account ID for Git identity"
            )
        validated_email = validate_git_author_email(
            f"{account_id}+{login}@users.noreply.github.com"
        )
    return {"name": validated_name, "email": validated_email}


def _set_git_identity_value(config: SetupConfig, key: str, value: str) -> None:
    result = _run_as_login_user(
        config.username,
        _user_home(config),
        f"git config --global {shlex.quote(key)} {shlex.quote(value)}",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git config failed").strip()
        raise RuntimeError(f"Could not configure target Git identity: {detail}")


def _configure_git_identity(config: SetupConfig) -> None:
    """Fill missing target Git author fields from controller or GitHub identity."""

    existing = {
        "name": _configured_git_identity_value(config, "user.name"),
        "email": _configured_git_identity_value(config, "user.email"),
    }
    missing = [field for field, value in existing.items() if value is None]
    if not missing:
        print("  Existing Git author identity retained")
        return

    identity = _git_identity_payload()
    if any(field not in identity for field in missing):
        github_identity = _github_git_identity(config)
        for field in missing:
            identity.setdefault(field, github_identity[field])

    keys = {"name": "user.name", "email": "user.email"}
    for field in missing:
        _set_git_identity_value(config, keys[field], identity[field])
    print("  Configured Git author identity")


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
    """Seed a missing selected host without replacing target-maintained auth."""
    user_home = _user_home(config)
    destination = os.path.join(user_home, ".config", "gh", "hosts.yml")
    _reject_symlinked_agent_destination(os.path.dirname(destination))
    _ensure_agent_directory(os.path.dirname(destination))
    _chown_user_directory_chain(config, user_home, os.path.dirname(destination))
    new_entry = _payload_host_entry(source, config.git_host)
    existing = ""
    if os.path.lexists(destination):
        if os.path.islink(destination) or not os.path.isfile(destination):
            raise RuntimeError(f"Refusing unsafe GitHub credentials: {destination}")
        with open(destination, encoding="utf-8") as file_obj:
            existing = file_obj.read()

    lines = existing.splitlines(keepends=True)
    selected_host_present = any(
        line.startswith(f"{config.git_host}:")
        or line.startswith(f"'{config.git_host}':")
        or line.startswith(f'"{config.git_host}":')
        for line in lines
    )
    if selected_host_present:
        os.chmod(destination, 0o600)
        _chown_path(config, destination)
        print(
            "  Existing GitHub CLI credentials retained; setup seeds missing "
            "host credentials only"
        )
        return False

    merged = existing.rstrip("\n")
    if merged:
        merged += "\n"
    merged += new_entry

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
    """Apply uploaded config, seed missing credentials, and remove the payload."""
    if not os.path.isdir(REMOTE_AGENT_PAYLOAD_DIR):
        print("  No agent configuration payload found")
        return

    if is_dry_run():
        print("  [DRY-RUN] Would apply agent config and seed missing credentials")
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
                credential_tool="codex",
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
            _merge_github_credentials(config, gh_credentials)
            _configure_github_git_credentials(config)
            _configure_git_identity(config)
    finally:
        if os.path.isdir(REMOTE_AGENT_PAYLOAD_DIR):
            shutil.rmtree(REMOTE_AGENT_PAYLOAD_DIR)
            print("  Removed uploaded agent configuration payload")


def clone_agent_repositories(config: SetupConfig) -> None:
    """Clone requested HTTPS repositories as the target login user."""
    if not config.agent_repos:
        return
    repos_dir = config.agent_workspace or os.path.join(_user_home(config), "repos")
    if is_dry_run():
        for git_url in config.agent_repos:
            print(f"  [DRY-RUN] Would clone {git_url} to {repos_dir}")
        return

    from common.storage_steps import assert_declared_storage_mount

    assert_declared_storage_mount(config, repos_dir)
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
