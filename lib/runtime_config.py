"""Runtime configuration for storage operations.

This module provides a lightweight configuration class for runtime
operations (sync/scrub) that only includes fields needed by the
orchestrator and service tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any


@dataclass
class RuntimeConfig:
    """Lightweight runtime configuration for storage operations.

    This class provides type safety for runtime use (orchestrator, service tools)
    without the overhead of full SetupConfig which includes many setup-time
    options that aren't needed during periodic operations.

    Attributes:
        username: System user for file operations
        sync_specs: List of sync specifications [source, dest, interval]
        scrub_specs: List of scrub specifications [dir, db, redundancy, freq]
        notify_specs: List of notification specifications [type, target]
        smb_mounts: List of SMB mount specifications [mountpoint, ip, creds, share, subdir]
    """
    username: str
    sync_specs: list[list[str]]
    scrub_specs: list[list[str]]
    notify_specs: list[list[str]]
    smb_mounts: Optional[list[list[str]]] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeConfig":
        """Create RuntimeConfig from a dictionary (loaded from JSON state).

        Args:
            data: Dictionary containing config fields (typically from setup.json)

        Returns:
            RuntimeConfig instance
        """
        return cls(
            username=data.get("username", "root"),
            sync_specs=data.get("sync_specs") or [],
            scrub_specs=data.get("scrub_specs") or [],
            notify_specs=data.get("notify_specs") or [],
            smb_mounts=data.get("smb_mounts"),
        )

    @classmethod
    def from_setup_config(cls, config: Any) -> "RuntimeConfig":
        """Create RuntimeConfig from a SetupConfig instance.

        Args:
            config: SetupConfig instance from lib.config

        Returns:
            RuntimeConfig instance
        """
        return cls(
            username=config.username,
            sync_specs=config.sync_specs or [],
            scrub_specs=config.scrub_specs or [],
            notify_specs=config.notify_specs or [],
            smb_mounts=config.smb_mounts,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation
        """
        return {
            "username": self.username,
            "sync_specs": self.sync_specs,
            "scrub_specs": self.scrub_specs,
            "notify_specs": self.notify_specs,
            "smb_mounts": self.smb_mounts,
        }

    def has_storage_ops(self) -> bool:
        """Check if any storage operations are configured.

        Returns:
            True if sync or scrub specs are configured
        """
        return bool(self.sync_specs or self.scrub_specs)

    def get_all_paths(self) -> list[str]:
        """Get all unique paths from sync and scrub specs.

        Returns:
            Sorted list of unique paths
        """
        # Import here to avoid circular dependency
        from lib.task_utils import get_all_storage_paths
        return get_all_storage_paths(self)
