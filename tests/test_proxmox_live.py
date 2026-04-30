"""Live, end-to-end Proxmox container test.

This test creates a real LXC container on a Proxmox host, exercises the
management helpers in ``lib/proxmox_manage.py`` against it (status, list,
start, stop, health), and then destroys it. It is gated behind the
``live_proxmox`` expensive-test category so it never runs in the default
suite.

To run it manually::

    INFRA_TOOLS_RUN_LIVE_PROXMOX=1 \
    PROXMOX_TEST_HOST=10.0.0.10 \
    PROXMOX_TEST_USER=root \
    PROXMOX_TEST_SSH_KEY=~/.ssh/proxmox_ed25519 \
    PROXMOX_TEST_TEMPLATE=local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
    PROXMOX_TEST_STORAGE=local-lvm \
    PROXMOX_TEST_BRIDGE=vmbr0 \
    PROXMOX_TEST_VMID=9999 \
    python3 -m unittest tests.test_proxmox_live

    # or via the runner:
    ./run_tests.py --expensive live_proxmox tests.test_proxmox_live

All ``PROXMOX_TEST_*`` env vars except ``PROXMOX_TEST_HOST`` and
``PROXMOX_TEST_TEMPLATE`` are optional and have sensible defaults.

The test always tries to destroy the container in tearDown, even if the test
body fails, so a failing run shouldn't leave debris behind.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.proxmox_hosts import ProxmoxHost
from lib.proxmox_manage import (
    ProxmoxManageError,
    _run_on_host,
    destroy_container,
    get_container_status,
    health_check,
    list_containers,
    start_container,
    stop_container,
)
from tests.expensive_support import expensive


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _required_env_missing() -> list[str]:
    missing: list[str] = []
    for var in ("PROXMOX_TEST_HOST", "PROXMOX_TEST_TEMPLATE"):
        if not _env(var):
            missing.append(var)
    return missing


@expensive(
    "live_proxmox",
    "Creates and destroys a real LXC container on a Proxmox host",
)
class TestProxmoxLiveLifecycle(unittest.TestCase):
    """Round-trip: create, list, start, stop, destroy a real container."""

    @classmethod
    def setUpClass(cls) -> None:
        missing = _required_env_missing()
        if missing:
            raise unittest.SkipTest(
                "Missing required env vars for live Proxmox test: "
                + ", ".join(missing)
            )
        cls.host = ProxmoxHost(
            name=_env("PROXMOX_TEST_HOST_NAME", "live-test"),
            address=_env("PROXMOX_TEST_HOST"),  # required, checked above
            user=_env("PROXMOX_TEST_USER", "root") or "root",
            ssh_key=_env("PROXMOX_TEST_SSH_KEY"),
        )
        cls.template = _env("PROXMOX_TEST_TEMPLATE")
        cls.storage = _env("PROXMOX_TEST_STORAGE", "local-lvm") or "local-lvm"
        cls.bridge = _env("PROXMOX_TEST_BRIDGE", "vmbr0") or "vmbr0"
        cls.vmid = int(_env("PROXMOX_TEST_VMID", "9999") or "9999")
        cls.hostname = _env(
            "PROXMOX_TEST_HOSTNAME", f"infra-tools-live-{cls.vmid}"
        ) or f"infra-tools-live-{cls.vmid}"
        cls.password = _env("PROXMOX_TEST_PASSWORD", "infra-tools-live") or "infra-tools-live"

    def setUp(self) -> None:
        # Ensure a clean slate: destroy any leftover container from a prior run.
        self._safe_destroy()

    def tearDown(self) -> None:
        self._safe_destroy()

    def _safe_destroy(self) -> None:
        try:
            destroy_container(self.host, self.vmid, force=True, purge=True)
        except ProxmoxManageError:
            # Container probably didn't exist; that's fine.
            pass

    def _create(self) -> None:
        cmd = (
            f"pct create {self.vmid} {self.template} "
            f"--hostname {self.hostname} "
            f"--memory 256 --cores 1 --rootfs {self.storage}:1 "
            f"--net0 name=eth0,bridge={self.bridge},ip=dhcp,type=veth "
            f"--password {self.password} --unprivileged 1 --start 0"
        )
        result = _run_on_host(self.host, cmd)
        if result.returncode != 0:
            self.fail(
                f"pct create failed (rc={result.returncode}): "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )

    def test_full_lifecycle(self) -> None:
        # Create
        self._create()

        # List should include our VMID
        containers = list_containers(self.host)
        vmids = {c.vmid for c in containers}
        self.assertIn(self.vmid, vmids, f"VMID {self.vmid} not in list: {vmids}")

        # Status should be 'stopped' right after creation (we passed --start 0)
        status = get_container_status(self.host, self.vmid)
        self.assertEqual(status, "stopped")

        # Start it
        start_container(self.host, self.vmid)
        self.assertEqual(get_container_status(self.host, self.vmid), "running")

        # Health check (best-effort - we don't require the container to be
        # pingable from the test runner since networking varies wildly).
        report = health_check(self.host, self.vmid, ssh_probe=False)
        self.assertEqual(report.status, "running")

        # Stop it gracefully
        stop_container(self.host, self.vmid)
        self.assertEqual(get_container_status(self.host, self.vmid), "stopped")

        # Destroy it
        destroy_container(self.host, self.vmid, purge=True)
        containers_after = list_containers(self.host)
        self.assertNotIn(
            self.vmid, {c.vmid for c in containers_after},
            "Container still present after destroy",
        )


if __name__ == "__main__":
    unittest.main()
