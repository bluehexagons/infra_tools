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
#
# ``bundler`` is included because Rails deployments (see lib/deployment.py)
# force ``TMPDIR=/var/tmp`` for ``bundle install``, which can leave
# ``bundlerYYYYMMDD-PID-RANDOM`` build directories behind when a deploy is
# interrupted. These are always safe to remove once they are a week old.
STALE_INFRA_TMP_MAX_AGE_DAYS = 7
INFRA_TMP_PREFIXES = (
    "infra_setup_build_",
    "infra_recall_",
    "infra_deploy_",
    "infra_tools_pubkey.",
    "antistatic-server-linux-",
    "antistatic-db-linux-",
    "bundler",
)

# Stale infra_tools temp cleanup scans both /tmp and /var/tmp because Rails
# deploys redirect bundler/gem build temp files to /var/tmp to avoid filling
# up small tmpfs-backed /tmp partitions.
INFRA_TMP_DIRS = ("/tmp", "/var/tmp")
