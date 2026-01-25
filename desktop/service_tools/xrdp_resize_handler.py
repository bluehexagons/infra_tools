#!/usr/bin/env python3
"""XRDP dynamic resolution helper.

Goal: make desktop sessions respond to RANDR screen-change events.

Notes:
- Runs as the session user.
- Designed to be safe in unprivileged containers (no privileged ops).
- Exits quietly if RANDR isn't available.
"""

from __future__ import annotations

import logging
import os
import select
import subprocess
import sys
import time
from logging.handlers import SysLogHandler


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("xrdp_resize_handler")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("xrdp_resize_handler: %(message)s")

    try:
        handler: logging.Handler = SysLogHandler(address="/dev/log")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    except Exception:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.propagate = False
    return logger


logger = _get_logger()


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from xrdp_utils import (  # noqa: E402
    get_current_resolution,
    get_rdp_output_name,
    is_resolution_valid,
    reset_resolution_to_auto,
    resolution_lock,
)


def _has_randr() -> bool:
    try:
        proc = subprocess.run(
            ["xrandr", "--current"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode != 0:
            return False
        if "RandR" in proc.stderr and "missing" in proc.stderr:
            return False
        return True
    except Exception:
        return False


def _refresh_desktop(desktop_session: str) -> None:
    try:
        if desktop_session == "xfce":
            subprocess.run(["xfdesktop", "--reload"], timeout=5, check=False)
            subprocess.run(["xfce4-panel", "-r"], timeout=5, check=False)
        elif desktop_session == "cinnamon":
            subprocess.run(
                [
                    "dbus-send",
                    "--session",
                    "--dest=org.Cinnamon",
                    "--type=method_call",
                    "/org/Cinnamon",
                    "org.Cinnamon.RestartCinnamon",
                ],
                timeout=5,
                check=False,
            )
        elif desktop_session == "i3":
            subprocess.run(["i3-msg", "restart"], timeout=5, check=False)
        else:
            rdp_output = get_rdp_output_name()
            reset_resolution_to_auto(rdp_output)
    except Exception as e:
        logger.info(f"desktop refresh failed: {e}")


def main() -> int:
    desktop_session = (os.environ.get("DESKTOP_SESSION") or "").lower()
    if "xfce" in desktop_session:
        desktop_session = "xfce"
    elif "cinnamon" in desktop_session:
        desktop_session = "cinnamon"
    elif "i3" in desktop_session:
        desktop_session = "i3"
    else:
        desktop_session = "generic"

    if not _has_randr():
        logger.info("RANDR not available; exiting")
        return 0

    # xev is the cheapest way to get RANDR change events.
    try:
        subprocess.run(["which", "xev"], capture_output=True, timeout=2, check=True)
    except Exception:
        logger.info("xev not found; exiting")
        return 0

    logger.info(f"started (DISPLAY={os.environ.get('DISPLAY', '')}, session={desktop_session})")

    last_resolution: str | None = None
    last_action_ts = 0.0

    proc = None
    try:
        proc = subprocess.Popen(
            ["xev", "-root", "-event", "randr"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        # Startup sanity: avoid being stuck in an invalid size.
        time.sleep(1)
        cur = get_current_resolution()
        if not is_resolution_valid(cur):
            with resolution_lock("resize-startup", timeout=2.0) as acquired:
                if acquired:
                    reset_resolution_to_auto(get_rdp_output_name())

        while True:
            if proc.poll() is not None:
                break

            if not proc.stdout:
                time.sleep(1)
                continue

            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue

            line = proc.stdout.readline()
            if not line:
                break

            if "RRScreenChangeNotify" not in line:
                continue

            # Debounce: events can arrive in bursts.
            now = time.time()
            if now - last_action_ts < 0.75:
                continue

            cur = get_current_resolution()
            if cur and cur == last_resolution:
                continue

            with resolution_lock("resize-event", timeout=2.0) as acquired:
                if not acquired:
                    continue
                time.sleep(0.25)
                _refresh_desktop(desktop_session)

            last_resolution = cur
            last_action_ts = now

    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.info(f"error: {e}")
        return 1
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
