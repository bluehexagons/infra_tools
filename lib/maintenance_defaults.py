"""Shared defaults for maintenance and cleanup tasks."""

from __future__ import annotations

from lib.types import BYTES_PER_GB

JOURNAL_MAX_USE = "100M"
JOURNAL_MAX_AGE = "30d"
STALE_CRASH_REPORT_MAX_AGE_DAYS = 30
CRASH_REPORT_DIRS = ("/var/crash", "/var/lib/systemd/coredump")
CRASH_REPORT_PATTERNS = (
    r"core\..+",
    r".+\.(?:crash|upload|uploaded)",
)
STORAGE_WARNING_PERCENT = 80
STORAGE_CRITICAL_PERCENT = 90

# Wait up to 5 minutes for apt/dpkg locks to be released before failing.
APT_LOCK_OPTIONS = [
    "-o", "DPkg::Lock::Timeout=300",
]

# Individual cleanup commands should never block the whole maintenance run forever.
CLEANUP_COMMAND_TIMEOUT_SECONDS = 600

# User-scoped cache maintenance runs independently from privileged host
# cleanup. Pruning commands run every week, while full cache eviction is
# reserved for these bounded size/age thresholds.
NPM_CACHE_MAX_BYTES = 2 * BYTES_PER_GB
PIP_CACHE_MAX_BYTES = 2 * BYTES_PER_GB
GO_BUILD_CACHE_MAX_BYTES = 2 * BYTES_PER_GB
GO_MODULE_CACHE_MAX_BYTES = 5 * BYTES_PER_GB
OPENCODE_CACHE_MAX_BYTES = 2 * BYTES_PER_GB
CODEX_CACHE_MAX_BYTES = BYTES_PER_GB
STALE_USER_TOOL_CACHE_MAX_AGE_DAYS = 90
STALE_USER_TOOL_TMP_MAX_AGE_DAYS = 7

# Remove infra_tools-owned temp artifacts after a week. These are normally
# cleaned up by finally blocks, but interrupted setup/deploy/provision runs can
# leave them behind.
#
# The Bundler pattern is included because Rails deployments (see lib/deployment.py)
# force ``TMPDIR=/var/tmp`` for ``bundle install``, which can leave
# ``bundlerYYYYMMDD-PID-RANDOM`` build directories behind when a deploy is
# interrupted. These are always safe to remove once they are a week old.
STALE_INFRA_TMP_MAX_AGE_DAYS = 7
INFRA_TMP_PATTERNS = (
    r"infra_setup_build_[A-Za-z0-9_-]+",
    r"infra_recall_[A-Za-z0-9_-]+",
    r"infra_deploy_[A-Za-z0-9_-]+",
    r"infra_tools_pubkey\.[A-Za-z0-9]+",
    r"antistatic-(?:server|db)-linux-(?:amd64|arm64)\.v[A-Za-z0-9._-]+",
    r"bundler\d{8}-\d+-[A-Za-z0-9_-]+",
)
# Stale infra_tools temp cleanup scans both /tmp and /var/tmp because Rails
# deploys redirect bundler/gem build temp files to /var/tmp to avoid filling
# up small tmpfs-backed /tmp partitions.
INFRA_TMP_DIRS = ("/tmp", "/var/tmp")
