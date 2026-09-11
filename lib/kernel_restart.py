"""Kernel restart markers and conservative Proxmox update advisories."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from lib.atomic_io import write_text_atomic
from lib.validation import validate_filesystem_path

KERNEL_HOOK = "/etc/kernel/postinst.d/infra-tools-reboot-required"
_PVE_RELEASE = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)-([0-9]+)-pve")

# Keep this hook independent of /opt, Python imports, and unattended-upgrades:
# package configuration must also work while infra-tools is being replaced.
KERNEL_HOOK_CONTENT = """#!/bin/sh
# Managed by infra-tools. Kernel package post-install hook.
set -eu
case "${1:-}" in
    ''|*[!a-zA-Z0-9.+_-]*) exit 0 ;;
esac
[ "$1" != "$(uname -r)" ] || exit 0
case "${DPKG_MAINTSCRIPT_PACKAGE:-}" in
    ''|*[!a-zA-Z0-9.+:-]*) package="kernel-$1" ;;
    *) package="$DPKG_MAINTSCRIPT_PACKAGE" ;;
esac
touch /run/reboot-required
if ! grep -Fqx -- "$package" /run/reboot-required.pkgs 2>/dev/null; then
    printf '%s\\n' "$package" >> /run/reboot-required.pkgs
fi
"""


def install_kernel_restart_hook() -> None:
    """Install the executable marker hook, preserving other packages' hooks."""
    validate_filesystem_path(KERNEL_HOOK, must_exist=False)
    write_text_atomic(KERNEL_HOOK, KERNEL_HOOK_CONTENT, mode=0o755)


def newer_proxmox_kernel() -> str | None:
    """Find a newer configured PVE kernel with a boot image.

    This is advisory evidence only: package presence does not establish what
    GRUB or proxmox-boot-tool will boot, especially with a deliberate pin.
    Query failures are raised so callers cannot report a false all-clear.
    """
    running = _PVE_RELEASE.fullmatch(os.uname().release)
    if running is None:
        return None
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status} ${Package}\\n"],
        check=True, capture_output=True, text=True, timeout=30,
    )
    current = tuple(map(int, running.groups()))
    candidates: list[tuple[tuple[int, ...], str]] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[0] != "installed":
            continue
        package = fields[1]
        for prefix in ("proxmox-kernel-", "pve-kernel-"):
            if not package.startswith(prefix):
                continue
            release = package[len(prefix):].removesuffix("-signed")
            match = _PVE_RELEASE.fullmatch(release)
            if match is None:
                continue
            version = tuple(map(int, match.groups()))
            image = f"/boot/vmlinuz-{release}"
            validate_filesystem_path(image, must_exist=False)
            if version > current and Path(image).is_file():
                candidates.append((version, release))
    return max(candidates)[1] if candidates else None
