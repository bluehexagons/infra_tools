"""Shared defaults for maintenance and cleanup tasks."""

from __future__ import annotations

JOURNAL_MAX_USE = "100M"

# Wait up to 5 minutes for apt/dpkg locks to be released before failing.
APT_LOCK_OPTIONS = [
    "-o", "DPkg::Lock::Timeout=300",
]

# Individual cleanup commands should never block the whole maintenance run forever.
CLEANUP_COMMAND_TIMEOUT_SECONDS = 600

# Remove infra_tools-owned temp artifacts after a week. These are normally
# cleaned up by finally blocks, but interrupted setup/deploy/provision runs can
# leave them behind.
STALE_INFRA_TMP_MAX_AGE_DAYS = 7
INFRA_TMP_PREFIXES = (
    "infra_setup_build_",
    "infra_recall_",
    "infra_deploy_",
    "infra_tools_pubkey.",
    "antistatic-server-linux-",
    "antistatic-db-linux-",
)
