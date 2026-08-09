"""Persistent hostname and static network setup for Debian targets."""

from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import stat

from lib.atomic_io import write_text_atomic
from lib.config import SetupConfig
from lib.remote_utils import is_dry_run, run
from lib.types import MaybeStr, StrList
from lib.validation import (
    validate_network_interface_name,
    validate_network_setup_settings,
    validate_system_hostname,
)


NETWORKD_CONFIG_PATH = "/etc/systemd/network/00-infra-tools-static.network"
IFUPDOWN_MAIN_CONFIG_PATH = "/etc/network/interfaces"
IFUPDOWN_CONFIG_DIR = "/etc/network/interfaces.d"
IFUPDOWN_CONFIG_PATH = "/etc/network/interfaces.d/infra_tools_static"
CLOUD_INIT_CONFIG_DIR = "/etc/cloud/cloud.cfg.d"
CLOUD_INIT_NETWORK_CONFIG_PATH = "/etc/cloud/cloud.cfg.d/99-infra-tools-network.cfg"
CLOUD_INIT_HOSTNAME_CONFIG_PATH = "/etc/cloud/cloud.cfg.d/99-infra-tools-hostname.cfg"


def configure_system_hostname(config: SetupConfig) -> None:
    """Persist and immediately apply the requested system hostname."""

    if not config.system_hostname:
        return

    hostname = validate_system_hostname(config.system_hostname)
    if config.dry_run or is_dry_run():
        print(f"  [DRY-RUN] Would set system hostname to {hostname}")
        return

    run(f"hostnamectl set-hostname {shlex.quote(hostname)}")
    if os.path.isdir(CLOUD_INIT_CONFIG_DIR):
        write_text_atomic(
            CLOUD_INIT_HOSTNAME_CONFIG_PATH,
            "# Managed by infra_tools\npreserve_hostname: true\n",
            mode=0o644,
        )
    print(f"  ✓ System hostname set to {hostname}")


def _interface_from_route_output(output: str) -> MaybeStr:
    for line in output.splitlines():
        fields = line.split()
        try:
            candidate = fields[fields.index("dev") + 1]
        except (ValueError, IndexError):
            continue
        candidate = candidate.split("@", 1)[0]
        if candidate != "lo":
            return validate_network_interface_name(candidate)
    return None


def _resolve_network_interface(configured: MaybeStr) -> str:
    if configured:
        return validate_network_interface_name(configured)

    for command in (
        "ip -o route show default",
        "ip -o -6 route show default",
        "ip -o link show up",
    ):
        result = run(command, check=False, capture_output=True)
        interface = _interface_from_route_output(result.stdout or "")
        if interface:
            return interface
    raise RuntimeError(
        "Could not detect a network interface; specify one with --network-interface"
    )


def _command_available(command: str) -> bool:
    result = run(f"command -v {shlex.quote(command)}", check=False, capture_output=True)
    return result.returncode == 0


def _service_active(service: str) -> bool:
    result = run(
        f"systemctl is-active --quiet {shlex.quote(service)}",
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _detect_network_backend() -> str:
    if _command_available("nmcli") and _service_active("NetworkManager"):
        return "networkmanager"
    if _service_active("systemd-networkd"):
        return "networkd"
    if os.path.exists(IFUPDOWN_MAIN_CONFIG_PATH) or _command_available("ifup"):
        return "ifupdown"
    raise RuntimeError(
        "No supported active network backend found (NetworkManager, systemd-networkd, or ifupdown)"
    )


def _configure_networkmanager(config: SetupConfig, interface: str) -> None:
    result = run(
        f"nmcli -g GENERAL.CONNECTION device show {shlex.quote(interface)}",
        check=False,
        capture_output=True,
    )
    connection = (result.stdout or "").strip().splitlines()
    if result.returncode != 0 or not connection or connection[0] in {"", "--"}:
        raise RuntimeError(f"NetworkManager has no active connection for {interface}")
    connection_name = connection[0]
    quoted_connection = shlex.quote(connection_name)

    if config.static_ipv4:
        parts = [
            "nmcli connection modify",
            quoted_connection,
            "ipv4.method manual",
            f"ipv4.addresses {shlex.quote(config.static_ipv4)}",
            f"ipv4.gateway {shlex.quote(config.network_gateway4 or '')}",
            f"ipv4.never-default {'no' if config.network_gateway4 else 'yes'}",
        ]
        run(" ".join(parts))

    if config.static_ipv6:
        parts = [
            "nmcli connection modify",
            quoted_connection,
            "ipv6.method manual",
            f"ipv6.addresses {shlex.quote(config.static_ipv6)}",
            f"ipv6.gateway {shlex.quote(config.network_gateway6 or '')}",
            f"ipv6.never-default {'no' if config.network_gateway6 else 'yes'}",
        ]
        run(" ".join(parts))

    if config.network_dns is not None:
        ipv4_dns = [value for value in config.network_dns if ":" not in value]
        ipv6_dns = [value for value in config.network_dns if ":" in value]
        dns_parts = ["nmcli connection modify", quoted_connection]
        if ipv4_dns:
            dns_parts.extend(
                [
                    f"ipv4.dns {shlex.quote(','.join(ipv4_dns))}",
                    "ipv4.ignore-auto-dns yes",
                ]
            )
        if ipv6_dns:
            dns_parts.extend(
                [
                    f"ipv6.dns {shlex.quote(','.join(ipv6_dns))}",
                    "ipv6.ignore-auto-dns yes",
                ]
            )
        if len(dns_parts) > 2:
            run(" ".join(dns_parts))


def _render_networkd_config(config: SetupConfig, interface: str) -> str:
    lines = [
        "# Managed by infra_tools. Changes will be overwritten.",
        "[Match]",
        f"Name={interface}",
        "",
        "[Network]",
        "DHCP=ipv4" if not config.static_ipv4 else "DHCP=no",
        f"IPv6AcceptRA={'no' if config.static_ipv6 else 'yes'}",
    ]
    for address in (config.static_ipv4, config.static_ipv6):
        if address:
            lines.append(f"Address={address}")
    for gateway in (config.network_gateway4, config.network_gateway6):
        if gateway:
            lines.append(f"Gateway={gateway}")
    for dns_server in config.network_dns or []:
        lines.append(f"DNS={dns_server}")
    return "\n".join(lines) + "\n"


def _configure_networkd(config: SetupConfig, interface: str) -> None:
    write_text_atomic(
        NETWORKD_CONFIG_PATH,
        _render_networkd_config(config, interface),
        mode=0o644,
    )


def _strip_ifupdown_stanzas(content: str, interface: str) -> str:
    stanza_pattern = re.compile(
        rf"^\s*iface\s+{re.escape(interface)}\s+inet6?\s+\S+\s*(?:#.*)?$"
    )
    output: StrList = []
    skipping_stanza = False
    for line in content.splitlines(keepends=True):
        if skipping_stanza:
            if not line.strip() or line.startswith((" ", "\t")):
                continue
            skipping_stanza = False
        if stanza_pattern.match(line.rstrip("\r\n")):
            skipping_stanza = True
            continue
        output.append(line)
    return "".join(output)


def _write_with_backup(path: str, content: str) -> None:
    current_mode = 0o644
    if os.path.exists(path):
        current_mode = stat.S_IMODE(os.stat(path).st_mode)
        backup_path = f"{path}.infra-tools.bak"
        if not os.path.exists(backup_path):
            shutil.copy2(path, backup_path)
    write_text_atomic(path, content, mode=current_mode)


def _remove_existing_ifupdown_stanzas(interface: str) -> None:
    paths = [IFUPDOWN_MAIN_CONFIG_PATH]
    paths.extend(sorted(glob.glob(os.path.join(IFUPDOWN_CONFIG_DIR, "*"))))
    managed_path = os.path.abspath(IFUPDOWN_CONFIG_PATH)
    for path in paths:
        if (
            os.path.abspath(path) == managed_path
            or path.endswith(".infra-tools.bak")
            or not os.path.isfile(path)
        ):
            continue
        try:
            with open(path, "r", encoding="utf-8") as file_obj:
                original = file_obj.read()
        except OSError as exc:
            raise RuntimeError(f"Failed to read ifupdown config {path}: {exc}") from exc
        updated = _strip_ifupdown_stanzas(original, interface)
        if updated != original:
            _write_with_backup(path, updated)


def _ensure_ifupdown_include() -> None:
    source_line = f"source {IFUPDOWN_CONFIG_DIR}/*"
    if os.path.exists(IFUPDOWN_MAIN_CONFIG_PATH):
        with open(IFUPDOWN_MAIN_CONFIG_PATH, "r", encoding="utf-8") as file_obj:
            content = file_obj.read()
    else:
        content = "auto lo\niface lo inet loopback\n"
    include_pattern = re.compile(
        rf"^\s*(?:source\s+{re.escape(IFUPDOWN_CONFIG_DIR)}/\*|"
        rf"source-directory\s+{re.escape(IFUPDOWN_CONFIG_DIR)})\s*$",
        re.MULTILINE,
    )
    if include_pattern.search(content):
        return
    updated = content.rstrip() + f"\n\n{source_line}\n"
    _write_with_backup(IFUPDOWN_MAIN_CONFIG_PATH, updated)


def _render_ifupdown_config(config: SetupConfig, interface: str) -> str:
    lines = [
        "# Managed by infra_tools. Changes will be overwritten.",
        f"auto {interface}",
    ]
    if config.static_ipv4:
        lines.extend(
            [
                f"iface {interface} inet static",
                f"    address {config.static_ipv4}",
            ]
        )
        if config.network_gateway4:
            lines.append(f"    gateway {config.network_gateway4}")
    else:
        lines.append(f"iface {interface} inet dhcp")

    if config.network_dns:
        lines.append(f"    dns-nameservers {' '.join(config.network_dns)}")

    if config.static_ipv6:
        lines.extend(
            [
                "",
                f"iface {interface} inet6 static",
                f"    address {config.static_ipv6}",
            ]
        )
        if config.network_gateway6:
            lines.append(f"    gateway {config.network_gateway6}")
    else:
        lines.extend(["", f"iface {interface} inet6 auto"])
    return "\n".join(lines) + "\n"


def _configure_ifupdown(config: SetupConfig, interface: str) -> None:
    _ensure_ifupdown_include()
    write_text_atomic(
        IFUPDOWN_CONFIG_PATH,
        _render_ifupdown_config(config, interface),
        mode=0o644,
    )
    _remove_existing_ifupdown_stanzas(interface)


def _disable_cloud_init_networking() -> None:
    if not os.path.isdir(CLOUD_INIT_CONFIG_DIR):
        return
    write_text_atomic(
        CLOUD_INIT_NETWORK_CONFIG_PATH,
        "# Managed by infra_tools\nnetwork: {config: disabled}\n",
        mode=0o644,
    )


def configure_static_network(config: SetupConfig) -> None:
    """Persist static networking without interrupting the active SSH session."""

    if not (config.static_ipv4 or config.static_ipv6):
        return

    validate_network_setup_settings(config)
    if config.dry_run or is_dry_run():
        interface = config.network_interface or "<default-route-interface>"
        print(f"  [DRY-RUN] Would stage static network configuration for {interface}")
        return

    interface = _resolve_network_interface(config.network_interface)
    backend = _detect_network_backend()

    if backend == "networkmanager":
        _configure_networkmanager(config, interface)
    elif backend == "networkd":
        _configure_networkd(config, interface)
    else:
        _configure_ifupdown(config, interface)
    _disable_cloud_init_networking()

    print(
        f"  ✓ Static network configuration staged for {interface} via {backend}; "
        "it will take effect after reboot or an explicit interface restart"
    )
