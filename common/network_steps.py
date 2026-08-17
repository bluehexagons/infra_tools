"""Persistent hostname and static network setup for Debian targets."""

from __future__ import annotations

import glob
import ipaddress
import json
import os
import re
import shlex
import shutil
import stat
import sys

from lib.atomic_io import write_json_atomic, write_text_atomic
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
NETWORK_TRANSITION_PATH = "/run/infra-tools-network-transition.json"
NETWORK_TRANSITION_VERSION = 1
POLICY_TABLE_RANGE = range(20000, 20100)


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


def _reject_managed_bridge(interface: str) -> None:
    """Refuse generic edits to a bridge whose topology must be preserved."""

    if os.path.isdir(f"/sys/class/net/{interface}/bridge"):
        raise RuntimeError(
            f"Refusing generic static network changes for bridge {interface}; "
            "Proxmox and other bridge hosts require a topology-aware network plan"
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


def _persist_static_network(config: SetupConfig, interface: str, backend: str) -> None:
    if backend == "networkmanager":
        _configure_networkmanager(config, interface)
    elif backend == "networkd":
        _configure_networkd(config, interface)
    elif backend == "ifupdown":
        _configure_ifupdown(config, interface)
    else:
        raise RuntimeError(f"Unsupported pending network backend: {backend}")
    _disable_cloud_init_networking()


def _active_interface_addresses(interface: str, version: int) -> set[str]:
    family_flag = "-4" if version == 4 else "-6"
    family_name = "inet" if version == 4 else "inet6"
    result = run(
        f"ip -o {family_flag} address show dev {shlex.quote(interface)}",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not inspect IPv{version} addresses on {interface}: "
            f"{(result.stderr or '').strip() or 'ip command failed'}"
        )

    addresses: set[str] = set()
    for line in (result.stdout or "").splitlines():
        fields = line.split()
        try:
            address = fields[fields.index(family_name) + 1]
        except (ValueError, IndexError):
            continue
        addresses.add(str(ipaddress.ip_interface(address).ip))
    return addresses


def _select_policy_table(version: int) -> int:
    family_flag = "-4" if version == 4 else "-6"
    result = run(
        f"ip {family_flag} rule show",
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Could not inspect IPv{version} policy routing rules")

    used: set[int] = set()
    for line in (result.stdout or "").splitlines():
        priority_match = re.match(r"\s*(\d+):", line)
        table_match = re.search(r"\b(?:lookup|table)\s+(\d+)\b", line)
        if priority_match:
            used.add(int(priority_match.group(1)))
        if table_match:
            used.add(int(table_match.group(1)))

    for table in POLICY_TABLE_RANGE:
        if table in used:
            continue
        route_result = run(
            f"ip {family_flag} route show table {table}",
            check=False,
            capture_output=True,
        )
        if not (route_result.stdout or "").strip():
            return table
    raise RuntimeError(f"No unused IPv{version} policy routing table is available")


def _transition_addresses(
    config: SetupConfig,
) -> list[ipaddress.IPv4Interface | ipaddress.IPv6Interface]:
    return [
        ipaddress.ip_interface(value)
        for value in (config.static_ipv4, config.static_ipv6)
        if value
    ]


def _prepare_live_network_transition(
    config: SetupConfig,
    interface: str,
    backend: str,
) -> None:
    """Add requested addresses without removing the address carrying this SSH run."""

    if os.path.exists(NETWORK_TRANSITION_PATH):
        abort_network_transition()

    addresses = _transition_addresses(config)
    active_by_version = {
        version: _active_interface_addresses(interface, version)
        for version in {address.version for address in addresses}
    }
    added_addresses = [
        str(address)
        for address in addresses
        if str(address.ip) not in active_by_version[address.version]
    ]

    policy_tables: dict[str, int] = {}
    for version, gateway in (
        (4, config.network_gateway4),
        (6, config.network_gateway6),
    ):
        if gateway:
            policy_tables[str(version)] = _select_policy_table(version)

    payload = {
        "version": NETWORK_TRANSITION_VERSION,
        "backend": backend,
        "interface": interface,
        "static_ipv4": config.static_ipv4,
        "static_ipv6": config.static_ipv6,
        "gateway4": config.network_gateway4,
        "gateway6": config.network_gateway6,
        "dns": list(config.network_dns or []),
        "added_addresses": added_addresses,
        "policy_tables": policy_tables,
    }
    write_json_atomic(NETWORK_TRANSITION_PATH, payload, mode=0o600)

    try:
        for address in added_addresses:
            parsed = ipaddress.ip_interface(address)
            family_flag = "-4" if parsed.version == 4 else "-6"
            run(
                f"ip {family_flag} address add {shlex.quote(str(parsed))} "
                f"dev {shlex.quote(interface)}"
            )

        for address in addresses:
            gateway = (
                config.network_gateway4
                if address.version == 4
                else config.network_gateway6
            )
            if not gateway:
                continue
            family_flag = "-4" if address.version == 4 else "-6"
            host_prefix = 32 if address.version == 4 else 128
            table = policy_tables[str(address.version)]
            run(
                f"ip {family_flag} route replace table {table} "
                f"{shlex.quote(str(address.network))} dev {shlex.quote(interface)} "
                f"src {shlex.quote(str(address.ip))}"
            )
            run(
                f"ip {family_flag} route replace table {table} default via "
                f"{shlex.quote(gateway)} dev {shlex.quote(interface)}"
            )
            run(
                f"ip {family_flag} rule add priority {table} from "
                f"{shlex.quote(f'{address.ip}/{host_prefix}')} table {table}"
            )
    except Exception:
        abort_network_transition()
        raise


def _load_network_transition() -> tuple[SetupConfig, str, str, list[str], dict[str, int]]:
    try:
        with open(NETWORK_TRANSITION_PATH, "r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except FileNotFoundError as exc:
        raise RuntimeError("No pending network transition exists") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read pending network transition: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("version") != NETWORK_TRANSITION_VERSION:
        raise RuntimeError("Invalid pending network transition format")

    backend = payload.get("backend")
    if backend not in {"networkmanager", "networkd", "ifupdown"}:
        raise RuntimeError("Invalid pending network backend")
    interface_value = payload.get("interface")
    if not isinstance(interface_value, str):
        raise RuntimeError("Invalid pending network interface")
    interface = validate_network_interface_name(interface_value)

    string_fields: dict[str, MaybeStr] = {}
    for field in ("static_ipv4", "static_ipv6", "gateway4", "gateway6"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise RuntimeError(f"Invalid pending network field: {field}")
        string_fields[field] = value

    dns = payload.get("dns", [])
    if not isinstance(dns, list) or not all(isinstance(value, str) for value in dns):
        raise RuntimeError("Invalid pending DNS settings")

    config = SetupConfig(
        host="localhost",
        username="root",
        system_type="server_lite",
        static_ipv4=string_fields["static_ipv4"],
        static_ipv6=string_fields["static_ipv6"],
        network_gateway4=string_fields["gateway4"],
        network_gateway6=string_fields["gateway6"],
        network_dns=list(dns),
        network_interface=interface,
        activate_network=True,
    )
    validate_network_setup_settings(config)

    expected_addresses = {str(address) for address in _transition_addresses(config)}
    added_addresses = payload.get("added_addresses", [])
    if (
        not isinstance(added_addresses, list)
        or not all(isinstance(value, str) for value in added_addresses)
        or not set(added_addresses).issubset(expected_addresses)
    ):
        raise RuntimeError("Invalid pending added-address list")

    raw_tables = payload.get("policy_tables", {})
    if not isinstance(raw_tables, dict):
        raise RuntimeError("Invalid pending policy routing tables")
    policy_tables: dict[str, int] = {}
    for version, table in raw_tables.items():
        if version not in {"4", "6"} or not isinstance(table, int) or table not in POLICY_TABLE_RANGE:
            raise RuntimeError("Invalid pending policy routing table")
        policy_tables[version] = table

    return config, interface, backend, list(added_addresses), policy_tables


def commit_network_transition() -> None:
    """Persist a live transition only after the controller verified new-address SSH."""

    config, interface, backend, _added_addresses, _tables = _load_network_transition()
    _reject_managed_bridge(interface)
    _persist_static_network(config, interface, backend)
    os.unlink(NETWORK_TRANSITION_PATH)
    print(f"  ✓ Verified network transition persisted for {interface} via {backend}")


def abort_network_transition() -> None:
    """Remove temporary addresses and policy routes from an uncommitted transition."""

    if not os.path.exists(NETWORK_TRANSITION_PATH):
        return
    config, interface, _backend, added_addresses, policy_tables = _load_network_transition()

    for version, table in policy_tables.items():
        family_flag = "-4" if version == "4" else "-6"
        address_value = config.static_ipv4 if version == "4" else config.static_ipv6
        if not address_value:
            raise RuntimeError(f"Pending IPv{version} policy route has no source address")
        address = ipaddress.ip_interface(address_value)
        host_prefix = 32 if address.version == 4 else 128
        run(
            f"ip {family_flag} rule del priority {table} from "
            f"{shlex.quote(f'{address.ip}/{host_prefix}')} table {table}",
            check=False,
            capture_output=True,
        )
        run(
            f"ip {family_flag} route flush table {table}",
            check=False,
            capture_output=True,
        )

    for address in added_addresses:
        parsed = ipaddress.ip_interface(address)
        family_flag = "-4" if parsed.version == 4 else "-6"
        run(
            f"ip {family_flag} address del {shlex.quote(str(parsed))} "
            f"dev {shlex.quote(interface)}",
            check=False,
            capture_output=True,
        )
    os.unlink(NETWORK_TRANSITION_PATH)


def configure_static_network(config: SetupConfig) -> None:
    """Persist static networking without interrupting the active SSH session."""

    if not (config.static_ipv4 or config.static_ipv6):
        return

    validate_network_setup_settings(config)
    if config.dry_run or is_dry_run():
        interface = config.network_interface or "<default-route-interface>"
        action = "prepare and verify" if config.activate_network else "stage"
        print(f"  [DRY-RUN] Would {action} static network configuration for {interface}")
        return

    interface = _resolve_network_interface(config.network_interface)
    _reject_managed_bridge(interface)
    backend = _detect_network_backend()

    if config.activate_network:
        _prepare_live_network_transition(config, interface, backend)
        print(
            f"  ✓ Temporary addresses prepared for {interface}; retaining the current "
            "address while the controller verifies SSH"
        )
        return

    _persist_static_network(config, interface, backend)

    print(
        f"  ✓ Static network configuration staged for {interface} via {backend}; "
        "it will take effect after reboot or an explicit interface restart"
    )


def _network_transition_main(argv: list[str]) -> int:
    try:
        if argv == ["--commit-transition"]:
            commit_network_transition()
            return 0
        if argv == ["--abort-transition"]:
            abort_network_transition()
            return 0
        print("Usage: python3 -m common.network_steps --commit-transition|--abort-transition")
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Network transition failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_network_transition_main(sys.argv[1:]))
