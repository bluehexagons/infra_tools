"""Install and maintain the official Godot Engine Linux release."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import stat
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
from lib.remote_utils import is_dry_run, run


GODOT_GITHUB_REPO = "godotengine/godot"
GODOT_INSTALL_ROOT = "/opt/godot"
GODOT_RELEASES_DIR = f"{GODOT_INSTALL_ROOT}/releases"
GODOT_CURRENT_DIR = f"{GODOT_INSTALL_ROOT}/current"
GODOT_BINARY_LINK = "/usr/local/bin/godot"
GODOT4_BINARY_LINK = "/usr/local/bin/godot4"
GODOT_DESKTOP_FILE = "/usr/local/share/applications/org.godotengine.Godot.desktop"
GODOT_STATE_FILE = "/opt/infra_tools/state/godot.json"

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
