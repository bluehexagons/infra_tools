#!/usr/bin/env python3
"""XRDP utility functions.

These helpers are used by the XRDP session helper scripts.
They intentionally avoid privileged operations so they can run in
unprivileged containers.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import time
from contextlib import contextmanager
from typing import Generator


LOCK_DIR = "/tmp/xrdp-locks"


def ensure_lock_dir() -> None:
    try:
        os.makedirs(LOCK_DIR, mode=0o755, exist_ok=True)
    except Exception:
        # Fall back to /tmp if directory creation fails
        pass


def get_rdp_output_name() -> str:
    """Best-effort detection of the RDP output name (e.g. rdp0)."""
    try:
        result = subprocess.run(
            ["xrandr", "--current"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            match = re.search(r"^(rdp\d+)", result.stdout, re.MULTILINE)
            if match:
                return match.group(1)
    except Exception:
        pass
    return "default"


def get_current_resolution() -> str | None:
    """Return current resolution like '1920x1080' or None."""
    try:
        result = subprocess.run(
            ["xrandr", "--current"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            match = re.search(r"(\d+x\d+)", result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def is_resolution_valid(resolution: str | None) -> bool:
    if not resolution or resolution == "0x0":
        return False
    try:
        width_s, height_s = resolution.split("x", 1)
        width, height = int(width_s), int(height_s)
        return width > 0 and height > 0
    except Exception:
        return False


@contextmanager
def resolution_lock(operation: str, timeout: float = 5.0) -> Generator[bool, None, None]:
    """Coarse lock to avoid concurrent xrandr operations."""
    ensure_lock_dir()

    display = os.environ.get("DISPLAY", ":0")
    safe_display = display.replace(":", "_").replace(".", "_")
    lock_file = os.path.join(LOCK_DIR, f"xrdp-resolution-{safe_display}.lock")

    fd = None
    acquired = False
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o644)
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.ftruncate(fd, 0)
                    os.write(fd, f"{operation}:{os.getpid()}:{time.time()}\n".encode())
                except Exception:
                    pass
                break
            except BlockingIOError:
                time.sleep(0.1)
        yield acquired
    finally:
        if fd is not None:
            if acquired:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                os.close(fd)
            except Exception:
                pass


def reset_resolution_to_auto(rdp_output: str) -> bool:
    try:
        result = subprocess.run(
            ["xrandr", "--output", rdp_output, "--auto"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False
