#!/usr/bin/env python3
"""Curated catalog of Debian cloud images for VM provisioning.

The entries here pin a specific snapshot of a Debian generic-cloud image so that
``provision_vm`` produces reproducible results. Refresh with
``scripts/update_cloud_images.py``.

Only Debian is supported. Each ``base`` key maps to a snapshot dict containing:

- ``codename``: Debian release codename (``bookworm``, ``trixie``, ...).
- ``version``: Debian major version as a string.
- ``snapshot``: Upstream snapshot directory, e.g. ``20250115-2001``. ``latest``
  is allowed but discouraged because it floats.
- ``filename``: The qcow2 filename inside that snapshot directory.
- ``url``: Fully-qualified download URL to the qcow2.
- ``sha512``: Expected SHA-512 of the qcow2 (lowercase hex). Empty string
  disables the integrity check (only acceptable for ``snapshot == "latest"``).
"""

from __future__ import annotations

from typing import Optional, TypedDict


class CloudImage(TypedDict):
    codename: str
    version: str
    snapshot: str
    filename: str
    url: str
    sha512: str


DEFAULT_DEBIAN_BASE = "debian"

# NOTE: Refresh with `python3 scripts/update_cloud_images.py`. The script
# overwrites the dictionary literal below; preserve the ``# BEGIN/END
# CLOUD_IMAGES`` markers.

# BEGIN CLOUD_IMAGES
CLOUD_IMAGES: dict[str, CloudImage] = {
    "debian": {
        "codename": "bookworm",
        "version": "12",
        "snapshot": "20260806-2562",
        "filename": "debian-12-genericcloud-amd64-20260806-2562.qcow2",
        "url": "https://cloud.debian.org/images/cloud/bookworm/20260806-2562/debian-12-genericcloud-amd64-20260806-2562.qcow2",
        "sha512": "3622c990108a044ed411652f8741e77c5822c365114d7b940206b243f8fb617b8586792df4cdb7afba1b71d1a09289d8ed632124688f2c8352cb08190a1e9868",
    },
    "debian-12": {
        "codename": "bookworm",
        "version": "12",
        "snapshot": "20260806-2562",
        "filename": "debian-12-genericcloud-amd64-20260806-2562.qcow2",
        "url": "https://cloud.debian.org/images/cloud/bookworm/20260806-2562/debian-12-genericcloud-amd64-20260806-2562.qcow2",
        "sha512": "3622c990108a044ed411652f8741e77c5822c365114d7b940206b243f8fb617b8586792df4cdb7afba1b71d1a09289d8ed632124688f2c8352cb08190a1e9868",
    },
    "debian-13": {
        "codename": "trixie",
        "version": "13",
        "snapshot": "20260803-2559",
        "filename": "debian-13-genericcloud-amd64-20260803-2559.qcow2",
        "url": "https://cloud.debian.org/images/cloud/trixie/20260803-2559/debian-13-genericcloud-amd64-20260803-2559.qcow2",
        "sha512": "769562604ecaac26b661167891ef922f71f4d87d50a11423fc04e51444fda0d882c87996dd1181170d233627f4728e6722db2695c0ef753dad762c4ac4ed32e1",
    },
}
# END CLOUD_IMAGES


def resolve_cloud_image(base: str) -> CloudImage:
    """Return the catalog entry for ``base`` (case-insensitive)."""
    key = (base or "").strip().lower()
    if not key:
        key = DEFAULT_DEBIAN_BASE
    if key in CLOUD_IMAGES:
        return CLOUD_IMAGES[key]
    raise ValueError(
        f"No cloud image registered for base {base!r}. "
        f"Known: {', '.join(sorted(CLOUD_IMAGES))}"
    )


def list_cloud_images() -> list[tuple[str, CloudImage]]:
    """Return all catalog entries, sorted by key."""
    return sorted(CLOUD_IMAGES.items())


def cloud_image_local_filename(image: CloudImage) -> str:
    """Return the on-host filename used after download into the ISO storage."""
    return image["filename"]


def is_local_image_ref(ref: str) -> bool:
    """True when ``ref`` is a Proxmox ISO storage reference."""
    if not ref:
        return False
    if ":" not in ref:
        return False
    head, _, tail = ref.partition(":")
    if not head or not tail:
        return False
    return tail.startswith("iso/") and len(tail) > len("iso/")


def parse_image_argument(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split ``--image`` into ``(url, storage_ref)``.

    Returns a ``(url, None)`` tuple when ``value`` is an http(s) URL, a
    ``(None, storage_ref)`` tuple when it looks like ``storage:iso/foo.qcow2``,
    or ``(None, None)`` when ``value`` is empty.
    """
    if not value:
        return None, None
    stripped = value.strip()
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return stripped, None
    if is_local_image_ref(stripped):
        return None, stripped
    raise ValueError(
        f"Invalid --image value: {value!r}. "
        "Expected an http(s) URL or a Proxmox storage reference like "
        "'local:iso/foo.qcow2'."
    )
