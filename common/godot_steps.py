"""Install and maintain the official Godot Engine Linux release."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import stat
import tarfile
import tempfile
import zipfile
from typing import Any, Mapping

from lib.atomic_io import write_text_atomic
from lib.config import SetupConfig
from lib.maintenance_systemd import configure_maintenance_timer
from lib.release_management import (
    detect_release_arch,
    fetch_latest_verified_github_release_asset,
    load_json_state,
    validate_release_tag,
    write_json_state,
)
from lib.remote_utils import get_user_home, is_dry_run, run
from lib.validation import validate_filesystem_path
from lib.validators import validate_username

from .common_steps import _run_as_login_user


GODOT_GITHUB_REPO = "godotengine/godot"
GODOT_INSTALL_ROOT = "/opt/godot"
GODOT_RELEASES_DIR = f"{GODOT_INSTALL_ROOT}/releases"
GODOT_CURRENT_DIR = f"{GODOT_INSTALL_ROOT}/current"
GODOT_BINARY_LINK = "/usr/local/bin/godot"
GODOT4_BINARY_LINK = "/usr/local/bin/godot4"
GODOT_DESKTOP_FILE = "/usr/local/share/applications/org.godotengine.Godot.desktop"
GODOT_STATE_FILE = "/opt/infra_tools/state/godot.json"
GODOT_BUNDLE_STATE_FILE = "/opt/infra_tools/state/godot-bundles.json"
GODOT_EXPORT_TEMPLATE_ROOT = f"{GODOT_INSTALL_ROOT}/export_templates"
GODOT_EXPORT_TEMPLATE_RELEASES_DIR = f"{GODOT_EXPORT_TEMPLATE_ROOT}/releases"

BUTLER_GITHUB_REPO = "itchio/butler"
BUTLER_INSTALL_ROOT = "/opt/butler"
BUTLER_RELEASES_DIR = f"{BUTLER_INSTALL_ROOT}/releases"
BUTLER_CURRENT_DIR = f"{BUTLER_INSTALL_ROOT}/current"
BUTLER_BINARY_LINK = "/usr/local/bin/butler"
BUTLER_STATE_FILE = "/opt/infra_tools/state/butler.json"

STEAMCMD_BOOTSTRAP_URL = (
    "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
)
STEAMCMD_BOOTSTRAP_SHA256 = (
    "cebf0046bfd08cf45da6bc094ae47aa39ebf4155e5ede41373b579b8f1071e7c"
)

_GODOT_WEB_TEMPLATE_FILES = (
    "web_debug.zip",
    "web_release.zip",
    "web_dlink_debug.zip",
    "web_dlink_release.zip",
    "web_nothreads_debug.zip",
    "web_nothreads_release.zip",
    "web_dlink_nothreads_debug.zip",
    "web_dlink_nothreads_release.zip",
)
_STEAMCMD_BOOTSTRAP_FILES = {
    "steamcmd.sh": 0o755,
    "linux32/steamcmd": 0o755,
    "linux32/steamerrorreporter": 0o755,
    "linux32/libstdc++.so.6": 0o755,
    "linux32/crashhandler.so": 0o755,
}

_GODOT_DESKTOP_ENTRY = f"""[Desktop Entry]
Name=Godot Engine
GenericName=Game Engine
Comment=Create 2D and 3D games
Exec={GODOT_BINARY_LINK} --editor %f
Icon=godot
Terminal=false
Type=Application
MimeType=application/x-godot-project;
Categories=Development;IDE;
StartupWMClass=Godot
"""


def _godot_asset_arch(release_arch: str) -> str:
    """Translate the shared release architecture to Godot's asset suffix."""
    architecture_map = {
        "amd64": "x86_64",
        "arm64": "arm64",
    }
    try:
        return architecture_map[release_arch]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported Godot architecture: {release_arch}") from exc


def _godot_release_dir(tag_name: str, archive_sha256: str) -> str:
    """Return the immutable directory for one verified Godot release."""
    safe_tag = validate_release_tag(tag_name)
    if len(archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in archive_sha256
    ):
        raise ValueError("Invalid Godot release SHA-256")
    return f"{GODOT_RELEASES_DIR}/{safe_tag}-{archive_sha256[:12]}"


def fetch_latest_godot_release(asset_arch: str) -> tuple[str, str, str]:
    """Return the latest stable Godot tag, asset URL, and publisher digest."""
    asset_suffix = f"_linux.{asset_arch}.zip"
    return fetch_latest_verified_github_release_asset(
        GODOT_GITHUB_REPO,
        asset_matches=lambda tag_name, asset_name: (
            asset_name == f"Godot_v{tag_name}{asset_suffix}"
        ),
        missing_asset_description=(
            f"No verified stable Godot Linux asset found for architecture '{asset_arch}'"
        ),
    )


def read_godot_state() -> Mapping[str, Any]:
    """Return persisted Godot installation metadata."""
    return load_json_state(
        GODOT_STATE_FILE,
        read_error_label="Godot state file",
        invalid_state_message="Invalid Godot state file contents",
    )


def write_godot_state(tag_name: str, archive_sha256: str) -> None:
    """Persist the active verified Godot release."""
    write_json_state(
        GODOT_STATE_FILE,
        {"tag_name": tag_name, "archive_sha256": archive_sha256},
        mode=0o600,
    )


def read_godot_bundle_state() -> Mapping[str, Any]:
    """Return registered bundle selections and target users."""
    return load_json_state(
        GODOT_BUNDLE_STATE_FILE,
        read_error_label="Godot bundle state file",
        invalid_state_message="Invalid Godot bundle state file contents",
    )


def write_godot_bundle_state(bundles: list[str], users: list[str]) -> None:
    """Persist bundle selections used by recurring maintenance."""
    write_json_state(
        GODOT_BUNDLE_STATE_FILE,
        {"bundles": bundles, "users": users},
        mode=0o600,
    )


def read_butler_state() -> Mapping[str, Any]:
    """Return persisted Butler installation metadata."""
    return load_json_state(
        BUTLER_STATE_FILE,
        read_error_label="Butler state file",
        invalid_state_message="Invalid Butler state file contents",
    )


def write_butler_state(tag_name: str, archive_sha256: str) -> None:
    """Persist the active verified Butler release."""
    write_json_state(
        BUTLER_STATE_FILE,
        {"tag_name": tag_name, "archive_sha256": archive_sha256},
        mode=0o600,
    )


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        while chunk := file_obj.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_verified_binary(
    archive_path: str,
    *,
    expected_sha256: str,
    binary_member: str,
    release_dir: str,
) -> str:
    """Verify a Godot archive and atomically stage its one expected binary."""
    if _sha256_file(archive_path) != expected_sha256:
        raise RuntimeError("Godot release archive checksum verification failed")

    os.makedirs(release_dir, mode=0o755, exist_ok=True)
    binary_path = os.path.join(release_dir, "godot")
    temporary_path = ""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            try:
                member = archive.getinfo(binary_member)
            except KeyError as exc:
                raise RuntimeError(
                    f"Godot release archive is missing {binary_member}"
                ) from exc
            member_mode = member.external_attr >> 16
            member_type = stat.S_IFMT(member_mode)
            if member.is_dir() or member_type not in (0, stat.S_IFREG):
                raise RuntimeError("Godot release binary is not a regular file")
            with archive.open(member) as source, tempfile.NamedTemporaryFile(
                mode="wb",
                dir=release_dir,
                prefix=".godot-",
                delete=False,
            ) as destination:
                temporary_path = destination.name
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
        os.chmod(temporary_path, 0o755)
        os.replace(temporary_path, binary_path)
        temporary_path = ""
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
    return binary_path


def _validate_archive_digest(archive_path: str, expected_sha256: str, label: str) -> None:
    """Require an archive to match its expected hexadecimal SHA-256."""
    if _sha256_file(archive_path) != expected_sha256:
        raise RuntimeError(f"{label} archive checksum verification failed")


def _godot_template_version(tag_name: str) -> str:
    """Return Godot's version-specific export-template directory name."""
    safe_tag = validate_release_tag(tag_name)
    if not safe_tag.endswith("-stable"):
        raise ValueError(f"Unsupported Godot export-template tag: {tag_name}")
    return f"{safe_tag.removesuffix('-stable')}.stable"


def fetch_godot_export_templates(tag_name: str) -> tuple[str, str, str]:
    """Return the verified official template package matching an engine tag."""
    safe_tag = validate_release_tag(tag_name)
    return fetch_latest_verified_github_release_asset(
        GODOT_GITHUB_REPO,
        asset_matches=lambda release_tag, asset_name: (
            release_tag == safe_tag
            and asset_name == f"Godot_v{safe_tag}_export_templates.tpz"
        ),
        missing_asset_description=(
            f"No verified Godot export templates found for release '{safe_tag}'"
        ),
    )


def _godot_web_template_release_dir(
    template_version: str,
    archive_sha256: str,
) -> str:
    """Return the immutable cache directory for verified web templates."""
    validate_release_tag(template_version)
    if len(archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in archive_sha256
    ):
        raise ValueError("Invalid Godot export-template SHA-256")
    return (
        f"{GODOT_EXPORT_TEMPLATE_RELEASES_DIR}/"
        f"{template_version}-{archive_sha256[:12]}"
    )


def _web_template_release_complete(release_dir: str) -> bool:
    """Return whether every managed web-template file is present."""
    expected_files = ("version.txt", *_GODOT_WEB_TEMPLATE_FILES)
    return all(os.path.isfile(os.path.join(release_dir, name)) for name in expected_files)


def _extract_verified_web_templates(
    archive_path: str,
    *,
    expected_sha256: str,
    expected_version: str,
    release_dir: str,
) -> None:
    """Verify a TPZ and atomically cache only its web export templates."""
    _validate_archive_digest(archive_path, expected_sha256, "Godot export-template")
    expected_members = {
        "templates/version.txt": "version.txt",
        **{
            f"templates/{file_name}": file_name
            for file_name in _GODOT_WEB_TEMPLATE_FILES
        },
    }

    os.makedirs(GODOT_EXPORT_TEMPLATE_RELEASES_DIR, mode=0o755, exist_ok=True)
    staging_dir = tempfile.mkdtemp(
        prefix=".web-templates-",
        dir=GODOT_EXPORT_TEMPLATE_RELEASES_DIR,
    )
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member_name, destination_name in expected_members.items():
                try:
                    member = archive.getinfo(member_name)
                except KeyError as exc:
                    raise RuntimeError(
                        f"Godot export-template archive is missing {member_name}"
                    ) from exc
                member_mode = member.external_attr >> 16
                member_type = stat.S_IFMT(member_mode)
                if member.is_dir() or member_type not in (0, stat.S_IFREG):
                    raise RuntimeError(
                        f"Godot export-template member is not a regular file: {member_name}"
                    )
                destination_path = os.path.join(staging_dir, destination_name)
                with archive.open(member) as source, open(destination_path, "wb") as dest:
                    shutil.copyfileobj(source, dest)
                    dest.flush()
                    os.fsync(dest.fileno())
                os.chmod(destination_path, 0o644)

        version_path = os.path.join(staging_dir, "version.txt")
        with open(version_path, encoding="utf-8") as version_file:
            installed_version = version_file.read().strip()
        if installed_version != expected_version:
            raise RuntimeError(
                "Godot export-template version does not match the installed engine"
            )
        if os.path.exists(release_dir):
            if not _web_template_release_complete(release_dir):
                raise RuntimeError(
                    f"Existing Godot web-template cache is incomplete: {release_dir}"
                )
            return
        os.replace(staging_dir, release_dir)
        staging_dir = ""
    finally:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)


def _install_web_templates_for_user(
    username: str,
    template_version: str,
    release_dir: str,
) -> bool:
    """Copy cached web templates into one user's Godot data directory."""
    if not validate_username(username):
        raise ValueError(f"Invalid Godot bundle username: {username}")
    user_home = get_user_home(username)
    validate_filesystem_path(user_home, must_exist=True)
    destination_dir = os.path.join(
        user_home,
        ".local",
        "share",
        "godot",
        "export_templates",
        template_version,
    )
    was_complete = _web_template_release_complete(destination_dir)
    create_result = _run_as_login_user(
        username,
        user_home,
        f"install -d -m 0755 {shlex.quote(destination_dir)}",
        check=False,
        capture_output=True,
    )
    if create_result.returncode != 0:
        raise RuntimeError(f"Could not create Godot template directory for {username}")
    source_paths = [
        os.path.join(release_dir, name)
        for name in ("version.txt", *_GODOT_WEB_TEMPLATE_FILES)
    ]
    install_result = _run_as_login_user(
        username,
        user_home,
        "install -m 0644 "
        + " ".join(shlex.quote(path) for path in source_paths)
        + f" {shlex.quote(destination_dir)}/",
        check=False,
        capture_output=True,
    )
    if install_result.returncode != 0:
        detail = (
            install_result.stderr
            or install_result.stdout
            or "template installation failed"
        ).strip()
        raise RuntimeError(f"Could not install Godot web templates for {username}: {detail}")
    print(f"  ✓ Godot {template_version} web export templates installed for {username}")
    return not was_complete


def install_or_update_godot_web_bundle(username: str) -> bool:
    """Install verified web templates matching the active Godot release."""
    godot_state = read_godot_state()
    tag_name = godot_state.get("tag_name")
    if not isinstance(tag_name, str):
        raise RuntimeError("Godot must be installed before its web bundle")
    template_version = _godot_template_version(tag_name)
    _release_tag, download_url, expected_sha256 = fetch_godot_export_templates(
        tag_name
    )
    release_dir = _godot_web_template_release_dir(
        template_version,
        expected_sha256,
    )
    cache_changed = not _web_template_release_complete(release_dir)
    if cache_changed:
        with tempfile.TemporaryDirectory(
            prefix="infra-tools-godot-templates-"
        ) as temporary_dir:
            archive_path = os.path.join(temporary_dir, "export_templates.tpz")
            run(
                "curl -fL --proto '=https' --proto-redir '=https' "
                f"-o {shlex.quote(archive_path)} {shlex.quote(download_url)}",
                check=True,
                display_cmd=(
                    "curl -fL --proto '=https' --proto-redir '=https' "
                    f"-o {archive_path} <template URL>"
                ),
            )
            _extract_verified_web_templates(
                archive_path,
                expected_sha256=expected_sha256,
                expected_version=template_version,
                release_dir=release_dir,
            )
    user_changed = _install_web_templates_for_user(
        username,
        template_version,
        release_dir,
    )
    return cache_changed or user_changed


def _butler_release_dir(tag_name: str, archive_sha256: str) -> str:
    """Return the immutable directory for one verified Butler release."""
    safe_tag = validate_release_tag(tag_name)
    if len(archive_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in archive_sha256
    ):
        raise ValueError("Invalid Butler release SHA-256")
    return f"{BUTLER_RELEASES_DIR}/{safe_tag}-{archive_sha256[:12]}"


def fetch_latest_butler_release(asset_arch: str) -> tuple[str, str, str]:
    """Return the latest verified Butler release for a Linux architecture."""
    return fetch_latest_verified_github_release_asset(
        BUTLER_GITHUB_REPO,
        asset_matches=lambda _tag, asset_name: (
            asset_name == f"butler-linux-{asset_arch}.zip"
        ),
        missing_asset_description=(
            f"No verified Butler Linux asset found for architecture '{asset_arch}'"
        ),
    )


def _extract_verified_butler_archive(
    archive_path: str,
    *,
    expected_sha256: str,
    asset_arch: str,
    release_dir: str,
) -> None:
    """Verify and atomically stage the expected Butler runtime files."""
    _validate_archive_digest(archive_path, expected_sha256, "Butler release")
    expected_files = ("butler", "7z.so", "libc7zip.so")
    os.makedirs(BUTLER_RELEASES_DIR, mode=0o755, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=".butler-", dir=BUTLER_RELEASES_DIR)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for file_name in expected_files:
                member_name = f"linux-{asset_arch}/{file_name}"
                try:
                    member = archive.getinfo(member_name)
                except KeyError as exc:
                    raise RuntimeError(
                        f"Butler release archive is missing {member_name}"
                    ) from exc
                member_mode = member.external_attr >> 16
                member_type = stat.S_IFMT(member_mode)
                if member.is_dir() or member_type not in (0, stat.S_IFREG):
                    raise RuntimeError(
                        f"Butler release member is not a regular file: {member_name}"
                    )
                destination_path = os.path.join(staging_dir, file_name)
                with archive.open(member) as source, open(destination_path, "wb") as dest:
                    shutil.copyfileobj(source, dest)
                    dest.flush()
                    os.fsync(dest.fileno())
                os.chmod(destination_path, 0o755 if file_name == "butler" else 0o644)
        if os.path.exists(release_dir):
            if not all(
                os.path.isfile(os.path.join(release_dir, name))
                for name in expected_files
            ):
                raise RuntimeError(
                    f"Existing Butler release cache is incomplete: {release_dir}"
                )
            return
        os.replace(staging_dir, release_dir)
        staging_dir = ""
    finally:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)


def _managed_butler_release() -> str | None:
    """Return the active Butler release only when it is below the managed root."""
    current_binary = os.path.join(BUTLER_CURRENT_DIR, "butler")
    if not os.path.exists(current_binary):
        return None
    current_release = os.path.realpath(BUTLER_CURRENT_DIR)
    releases_root = os.path.realpath(BUTLER_RELEASES_DIR)
    try:
        if os.path.commonpath((current_release, releases_root)) != releases_root:
            return None
    except ValueError:
        return None
    return current_release


def _install_butler_links(release_dir: str) -> None:
    run(
        f"ln -sfn {shlex.quote(release_dir)} {shlex.quote(BUTLER_CURRENT_DIR)}",
        check=True,
    )
    run(
        f"ln -sfn {shlex.quote(BUTLER_CURRENT_DIR)}/butler "
        f"{shlex.quote(BUTLER_BINARY_LINK)}",
        check=True,
    )


def install_or_update_butler_release() -> tuple[str, bool, str]:
    """Install the newest verified Butler release system-wide."""
    asset_arch = detect_release_arch()
    tag_name, download_url, expected_sha256 = fetch_latest_butler_release(asset_arch)
    release_dir = _butler_release_dir(tag_name, expected_sha256)
    installed_state = read_butler_state()
    current_release = _managed_butler_release()
    expected_release = os.path.realpath(release_dir)
    current_binary = os.path.join(BUTLER_CURRENT_DIR, "butler")
    if (
        installed_state.get("tag_name") == tag_name
        and installed_state.get("archive_sha256") == expected_sha256
        and current_release == expected_release
        and os.path.exists(current_binary)
    ):
        _install_butler_links(release_dir)
        print(f"  ✓ Butler already up to date ({tag_name})")
        return tag_name, False, expected_sha256

    with tempfile.TemporaryDirectory(prefix="infra-tools-butler-release-") as temp_dir:
        archive_path = os.path.join(temp_dir, "butler.zip")
        run(
            "curl -fL --proto '=https' --proto-redir '=https' "
            f"-o {shlex.quote(archive_path)} {shlex.quote(download_url)}",
            check=True,
            display_cmd=(
                "curl -fL --proto '=https' --proto-redir '=https' "
                f"-o {archive_path} <release URL>"
            ),
        )
        _extract_verified_butler_archive(
            archive_path,
            expected_sha256=expected_sha256,
            asset_arch=asset_arch,
            release_dir=release_dir,
        )
        run(
            f"{shlex.quote(os.path.join(release_dir, 'butler'))} version",
            check=True,
            capture_output=True,
        )

    try:
        _install_butler_links(release_dir)
        write_butler_state(tag_name, expected_sha256)
    except Exception:
        if current_release and current_release != expected_release:
            _install_butler_links(current_release)
        raise
    print(f"  ✓ Installed Butler {tag_name} for itch.io publishing")
    return tag_name, True, expected_sha256


def _extract_steamcmd_bootstrap(archive_path: str, destination_dir: str) -> None:
    """Extract the pinned Valve bootstrap after strict member validation."""
    _validate_archive_digest(
        archive_path,
        STEAMCMD_BOOTSTRAP_SHA256,
        "SteamCMD bootstrap",
    )
    os.makedirs(destination_dir, mode=0o755, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        archive_members = archive.getmembers()
        members = {member.name: member for member in archive_members}
        if (
            len(archive_members) != len(_STEAMCMD_BOOTSTRAP_FILES)
            or set(members) != set(_STEAMCMD_BOOTSTRAP_FILES)
        ):
            raise RuntimeError("SteamCMD bootstrap archive has unexpected contents")
        for member_name, mode in _STEAMCMD_BOOTSTRAP_FILES.items():
            member = members[member_name]
            if not member.isfile():
                raise RuntimeError(
                    f"SteamCMD bootstrap member is not a regular file: {member_name}"
                )
            destination_path = os.path.join(destination_dir, member_name)
            os.makedirs(os.path.dirname(destination_path), mode=0o755, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError(f"Could not read SteamCMD member: {member_name}")
            with source, open(destination_path, "wb") as dest:
                shutil.copyfileobj(source, dest)
                dest.flush()
                os.fsync(dest.fileno())
            os.chmod(destination_path, mode)


def install_or_update_steamcmd(username: str) -> bool:
    """Install SteamCMD for one user and let its bootstrap self-update."""
    if detect_release_arch() != "amd64":
        print("  ⚠ SteamCMD is unavailable on Linux ARM64; Butler remains installed")
        return False
    if not validate_username(username):
        raise ValueError(f"Invalid SteamCMD username: {username}")
    user_home = get_user_home(username)
    validate_filesystem_path(user_home, must_exist=True)
    install_dir = os.path.join(
        user_home,
        ".local",
        "share",
        "infra_tools",
        "steamcmd",
    )
    launcher_dir = os.path.join(user_home, ".local", "bin")
    launcher_path = os.path.join(launcher_dir, "steamcmd")
    steamcmd_script = os.path.join(install_dir, "steamcmd.sh")
    changed = not os.path.isfile(steamcmd_script)
    if changed:
        with tempfile.TemporaryDirectory(
            prefix="infra-tools-steamcmd-bootstrap-"
        ) as temporary_dir:
            archive_path = os.path.join(temporary_dir, "steamcmd_linux.tar.gz")
            staging_dir = os.path.join(temporary_dir, "staging")
            run(
                "curl -fL --proto '=https' --proto-redir '=https' "
                f"-o {shlex.quote(archive_path)} {shlex.quote(STEAMCMD_BOOTSTRAP_URL)}",
                check=True,
            )
            _extract_steamcmd_bootstrap(archive_path, staging_dir)
            os.chmod(temporary_dir, 0o755)
            create_result = _run_as_login_user(
                username,
                user_home,
                f"install -d -m 0755 {shlex.quote(install_dir)} "
                f"{shlex.quote(os.path.join(install_dir, 'linux32'))} "
                f"{shlex.quote(launcher_dir)}",
                check=False,
                capture_output=True,
            )
            if create_result.returncode != 0:
                raise RuntimeError(f"Could not create SteamCMD directories for {username}")
            for member_name, mode in _STEAMCMD_BOOTSTRAP_FILES.items():
                source_path = os.path.join(staging_dir, member_name)
                destination_path = os.path.join(install_dir, member_name)
                install_result = _run_as_login_user(
                    username,
                    user_home,
                    f"install -m {mode:o} {shlex.quote(source_path)} "
                    f"{shlex.quote(destination_path)}",
                    check=False,
                    capture_output=True,
                )
                if install_result.returncode != 0:
                    raise RuntimeError(
                        f"Could not install SteamCMD bootstrap for {username}"
                    )

    link_result = _run_as_login_user(
        username,
        user_home,
        f"install -d -m 0755 {shlex.quote(launcher_dir)} && "
        f"ln -sfn {shlex.quote(steamcmd_script)} {shlex.quote(launcher_path)}",
        check=False,
        capture_output=True,
    )
    if link_result.returncode != 0:
        raise RuntimeError(f"Could not install SteamCMD launcher for {username}")
    update_result = _run_as_login_user(
        username,
        user_home,
        f"{shlex.quote(steamcmd_script)} +quit",
        check=False,
        capture_output=True,
    )
    if update_result.returncode != 0:
        detail = (
            update_result.stderr
            or update_result.stdout
            or "SteamCMD self-update failed"
        ).strip()
        raise RuntimeError(f"SteamCMD could not update for {username}: {detail}")
    print(f"  ✓ SteamCMD installed and updated for {username}")
    return changed


def _install_godot_links(release_dir: str) -> None:
    run(
        f"ln -sfn {shlex.quote(release_dir)} {shlex.quote(GODOT_CURRENT_DIR)}",
        check=True,
    )
    for link_path in (GODOT_BINARY_LINK, GODOT4_BINARY_LINK):
        run(
            f"ln -sfn {shlex.quote(GODOT_CURRENT_DIR)}/godot {shlex.quote(link_path)}",
            check=True,
        )


def _install_godot_desktop_entry() -> None:
    write_text_atomic(GODOT_DESKTOP_FILE, _GODOT_DESKTOP_ENTRY, mode=0o644)


def _managed_current_release() -> str | None:
    """Return the active release only when it is below the managed root."""
    current_binary = os.path.join(GODOT_CURRENT_DIR, "godot")
    if not os.path.exists(current_binary):
        return None
    current_release = os.path.realpath(GODOT_CURRENT_DIR)
    releases_root = os.path.realpath(GODOT_RELEASES_DIR)
    try:
        if os.path.commonpath((current_release, releases_root)) != releases_root:
            return None
    except ValueError:
        return None
    return current_release


def install_or_update_godot_release() -> tuple[str, bool, str]:
    """Install the newest verified stable Godot release."""
    release_arch = detect_release_arch()
    asset_arch = _godot_asset_arch(release_arch)
    tag_name, download_url, expected_sha256 = fetch_latest_godot_release(asset_arch)
    release_dir = _godot_release_dir(tag_name, expected_sha256)
    binary_member = f"Godot_v{tag_name}_linux.{asset_arch}"
    installed_state = read_godot_state()
    installed_tag = installed_state.get("tag_name")
    installed_digest = installed_state.get("archive_sha256")
    current_release = _managed_current_release()
    expected_release = os.path.realpath(release_dir)
    current_binary = os.path.join(GODOT_CURRENT_DIR, "godot")

    if (
        installed_tag == tag_name
        and installed_digest == expected_sha256
        and current_release == expected_release
        and os.path.exists(current_binary)
    ):
        _install_godot_links(release_dir)
        _install_godot_desktop_entry()
        print(f"  ✓ Godot already up to date ({tag_name})")
        return tag_name, False, expected_sha256

    if current_release == expected_release and os.path.exists(current_binary):
        raise RuntimeError(
            "Refusing to replace the active Godot release because its saved "
            "digest does not match; restore the managed Godot state before retrying"
        )

    os.makedirs(GODOT_RELEASES_DIR, mode=0o755, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="infra-tools-godot-release-") as temporary_dir:
        archive_path = os.path.join(temporary_dir, "godot.zip")
        run(
            "curl -fL --proto '=https' --proto-redir '=https' "
            f"-o {shlex.quote(archive_path)} {shlex.quote(download_url)}",
            check=True,
            display_cmd=(
                "curl -fL --proto '=https' --proto-redir '=https' "
                f"-o {archive_path} <release URL>"
            ),
        )
        release_binary = _extract_verified_binary(
            archive_path,
            expected_sha256=expected_sha256,
            binary_member=binary_member,
            release_dir=release_dir,
        )
        run(
            f"{shlex.quote(release_binary)} --headless --version",
            check=True,
            capture_output=True,
        )

    try:
        _install_godot_links(release_dir)
        _install_godot_desktop_entry()
        write_godot_state(tag_name, expected_sha256)
    except Exception:
        if current_release and current_release != expected_release:
            try:
                _install_godot_links(current_release)
            except Exception as rollback_exc:
                raise RuntimeError(
                    "Godot activation failed and the previous release could not be restored"
                ) from rollback_exc
        raise
    print(f"  ✓ Installed Godot {tag_name} for graphical and headless use")
    return tag_name, True, expected_sha256


def install_godot(config: SetupConfig) -> None:
    """Install Godot from its verified official release artifact."""
    del config
    if is_dry_run():
        print("  [DRY-RUN] Would install the latest stable Godot release")
        return
    run(
        "apt-get -o DPkg::Lock::Timeout=60 install -y -qq curl ca-certificates",
        check=True,
    )
    install_or_update_godot_release()


def _validated_registered_bundles() -> tuple[list[str], list[str]]:
    """Return validated bundle and user lists from root-owned state."""
    from lib.config import GODOT_BUNDLES

    state = read_godot_bundle_state()
    raw_bundles = state.get("bundles", [])
    raw_users = state.get("users", [])
    if not isinstance(raw_bundles, list) or not all(
        isinstance(bundle, str) and bundle in GODOT_BUNDLES
        for bundle in raw_bundles
    ):
        raise RuntimeError("Invalid Godot bundle selections in saved state")
    if not isinstance(raw_users, list) or not all(
        isinstance(username, str) and validate_username(username)
        for username in raw_users
    ):
        raise RuntimeError("Invalid Godot bundle users in saved state")
    bundles = [
        bundle for bundle in GODOT_BUNDLES if bundle in set(raw_bundles)
    ]
    users = list(dict.fromkeys(raw_users))
    return bundles, users


def _install_selected_godot_bundles(
    bundles: list[str],
    users: list[str],
) -> bool:
    """Install or update selected bundles for their registered users."""
    changed = False
    if "web" in bundles:
        for username in users:
            changed = install_or_update_godot_web_bundle(username) or changed
    if "publishing" in bundles:
        _butler_tag, butler_changed, _butler_sha256 = (
            install_or_update_butler_release()
        )
        changed = butler_changed or changed
        if detect_release_arch() == "amd64":
            run(
                "apt-get -o DPkg::Lock::Timeout=60 install -y -qq "
                "lib32gcc-s1 lib32stdc++6",
                check=True,
            )
        for username in users:
            changed = install_or_update_steamcmd(username) or changed
    return changed


def _register_godot_bundles(config: SetupConfig) -> tuple[list[str], list[str]]:
    """Merge a successful setup selection into recurring-maintenance state."""
    from lib.config import GODOT_BUNDLES

    existing_bundles, existing_users = _validated_registered_bundles()
    selected = set(existing_bundles)
    selected.update(config.godot_bundles or [])
    bundles = [bundle for bundle in GODOT_BUNDLES if bundle in selected]
    users = list(existing_users)
    if config.username not in users:
        users.append(config.username)
    write_godot_bundle_state(bundles, users)
    return bundles, users


def install_godot_bundles(config: SetupConfig) -> None:
    """Install repeatable Godot workflow bundles for the configured user."""
    bundles = list(config.godot_bundles or [])
    if not bundles:
        return
    if is_dry_run():
        print(f"  [DRY-RUN] Would install Godot bundles: {', '.join(bundles)}")
        return
    _install_selected_godot_bundles(bundles, [config.username])
    _register_godot_bundles(config)


def update_registered_godot_bundles() -> bool:
    """Reconcile saved Godot bundles during the weekly Godot update."""
    bundles, users = _validated_registered_bundles()
    if not bundles:
        return False
    if not users:
        raise RuntimeError("Godot bundles are registered without a target user")
    return _install_selected_godot_bundles(bundles, users)


def configure_auto_update_godot(config: SetupConfig) -> None:
    """Configure automatic stable Godot release updates."""
    del config
    configured = configure_maintenance_timer(
        service_name="auto-update-godot",
        service_desc="Auto-update Godot Engine",
        timer_desc="Auto-update Godot Engine weekly",
        script_path="/opt/infra_tools/common/service_tools/auto_update_godot.py",
        schedule="Sun *-*-* 06:30:00",
        check_path=GODOT_BINARY_LINK,
        check_name="Godot",
        purpose="auto-update",
    )
    if not configured:
        raise RuntimeError("Godot auto-update timer failed verification")
