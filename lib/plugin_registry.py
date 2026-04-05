"""Built-in plugin discovery and system type metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import importlib
import pkgutil
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    from collections.abc import Callable

    from lib.config import SetupConfig
    from lib.types import StepFunc

    StepBuilder = Callable[["SetupConfig"], list[tuple[str, StepFunc]]]


@dataclass(frozen=True)
class SystemTypeDefinition:
    """Plugin-owned metadata for a supported system type."""

    name: str
    description: str
    order: int
    include_desktop: bool = False
    include_cli_tools: bool = False
    include_desktop_apps: bool = False
    include_workstation_dev_apps: bool = False
    include_pc_dev_apps: bool = False
    include_web_server: bool = False
    include_web_firewall: bool = False
    default_enable_rdp: bool = False
    default_install_office: bool = False
    default_enable_smbclient: bool = False
    default_no_restart: bool = False
    default_browser: str | None = None
    step_builder: str | None = None


@dataclass(frozen=True)
class PluginDefinition:
    """Declarative plugin contract for built-in plugin discovery."""

    name: str
    module: str
    dependencies: tuple[str, ...] = ()
    system_types: tuple[SystemTypeDefinition, ...] = ()


@dataclass(frozen=True)
class PluginRegistry:
    """Resolved plugin registry with deterministic plugin and system-type order."""

    plugins: tuple[PluginDefinition, ...]
    system_types: tuple[SystemTypeDefinition, ...]
    system_types_by_name: Mapping[str, SystemTypeDefinition] = field(default_factory=dict)


def _discover_plugin_definitions(package_name: str = "plugins") -> list[PluginDefinition]:
    package = importlib.import_module(package_name)
    if not hasattr(package, "__path__"):
        raise ValueError(f"Plugin package {package_name!r} is not importable as a package")

    plugin_definitions: list[PluginDefinition] = []
    for _, module_name, is_package in sorted(pkgutil.iter_modules(package.__path__), key=lambda entry: entry[1]):
        if is_package:
            continue
        module = importlib.import_module(f"{package_name}.{module_name}")
        plugin_definition = getattr(module, "PLUGIN", None)
        if not isinstance(plugin_definition, PluginDefinition):
            raise ValueError(
                f"Plugin module {module.__name__!r} must define PLUGIN as PluginDefinition"
            )
        plugin_definitions.append(plugin_definition)
    return plugin_definitions


def build_plugin_registry(plugin_definitions: Sequence[PluginDefinition]) -> PluginRegistry:
    """Validate and resolve plugin definitions into a registry."""

    plugins_by_name: dict[str, PluginDefinition] = {}
    for plugin_definition in plugin_definitions:
        if plugin_definition.name in plugins_by_name:
            raise ValueError(f"Duplicate plugin name: {plugin_definition.name}")
        plugins_by_name[plugin_definition.name] = plugin_definition

    for plugin_definition in plugin_definitions:
        for dependency in plugin_definition.dependencies:
            if dependency not in plugins_by_name:
                raise ValueError(
                    f"Plugin {plugin_definition.name!r} depends on unknown plugin {dependency!r}"
                )

    resolved_plugins: list[PluginDefinition] = []
    pending_plugins = dict(plugins_by_name)
    resolved_names: set[str] = set()
    while pending_plugins:
        ready_plugins = sorted(
            (
                plugin_definition
                for plugin_definition in pending_plugins.values()
                if all(dependency in resolved_names for dependency in plugin_definition.dependencies)
            ),
            key=lambda plugin_definition: plugin_definition.name,
        )
        if not ready_plugins:
            cycle = ", ".join(sorted(pending_plugins))
            raise ValueError(f"Cyclic plugin dependencies detected: {cycle}")

        for plugin_definition in ready_plugins:
            resolved_plugins.append(plugin_definition)
            resolved_names.add(plugin_definition.name)
            del pending_plugins[plugin_definition.name]

    system_types_by_name: dict[str, SystemTypeDefinition] = {}
    ordered_system_types: list[SystemTypeDefinition] = []
    for plugin_definition in resolved_plugins:
        for system_type in plugin_definition.system_types:
            if system_type.name in system_types_by_name:
                existing = system_types_by_name[system_type.name]
                raise ValueError(
                    "Duplicate system type "
                    f"{system_type.name!r} from {plugin_definition.name!r}; "
                    f"already registered by {existing.description!r}"
                )
            system_types_by_name[system_type.name] = system_type
            ordered_system_types.append(system_type)

    ordered_system_types.sort(key=lambda system_type: (system_type.order, system_type.name))
    return PluginRegistry(
        plugins=tuple(resolved_plugins),
        system_types=tuple(ordered_system_types),
        system_types_by_name=system_types_by_name,
    )


@lru_cache(maxsize=1)
def get_plugin_registry() -> PluginRegistry:
    """Discover and cache the built-in plugin registry."""

    return build_plugin_registry(_discover_plugin_definitions())


def get_system_type_names() -> list[str]:
    """Return all registered system type names in display order."""

    return [system_type.name for system_type in get_plugin_registry().system_types]


def get_system_type_definition(system_type: str) -> SystemTypeDefinition:
    """Return metadata for a registered system type."""

    try:
        return get_plugin_registry().system_types_by_name[system_type]
    except KeyError as exc:
        raise ValueError(f"Unknown system type: {system_type!r}") from exc


def resolve_step_builder(system_type: str) -> "StepBuilder":
    """Resolve a system type's lazy step-builder reference."""

    definition = get_system_type_definition(system_type)
    if not definition.step_builder:
        raise ValueError(f"No step builder registered for system type: {system_type}")

    module_name, separator, function_name = definition.step_builder.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError(
            f"Invalid step builder reference for system type {system_type!r}: {definition.step_builder!r}"
        )

    module = importlib.import_module(module_name)
    builder = getattr(module, function_name, None)
    if builder is None or not callable(builder):
        raise ValueError(
            f"Step builder {definition.step_builder!r} for system type {system_type!r} is not callable"
        )
    return builder


def format_system_type_help(indent: str = "  ") -> str:
    """Return aligned help text for all registered system types."""

    system_types = get_plugin_registry().system_types
    if not system_types:
        return ""

    width = max(len(system_type.name) for system_type in system_types) + 2
    return "\n".join(
        f"{indent}{system_type.name.ljust(width)}{system_type.description}"
        for system_type in system_types
    )
