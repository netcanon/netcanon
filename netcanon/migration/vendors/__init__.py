"""
Vendor declarations — YAML-loaded at startup.

Each ``.yaml`` file in this directory defines a vendor identity for
the translator layer.  The :func:`load_vendors` function scans the
directory, validates each file against the :class:`VendorInfo`
pydantic model, and returns a registry keyed on ``vendor_id``.

Adding a new vendor is a 30-second operation:

1. Copy an existing ``.yaml`` file.
2. Change ``id``, ``display_name``, ``device_classes``, and ``notes``.
3. Restart.  The vendor appears in ``GET /api/v1/migration/adapters``
   and is available for codec ``vendor_id`` linking.

No Python code is involved — vendors are pure data.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ...models.migration import VendorInfo

logger = logging.getLogger(__name__)

_VENDORS_DIR = Path(__file__).parent


def load_vendors(
    vendors_dir: Path | None = None,
) -> dict[str, VendorInfo]:
    """Scan *vendors_dir* for ``.yaml`` files and return loaded vendors.

    Args:
        vendors_dir: Directory to scan.  Defaults to the built-in
            ``netcanon/migration/vendors/`` package directory.

    Returns:
        Mapping of ``vendor_id`` → ``VendorInfo``.  Vendors with
        duplicate ``id`` values are logged as warnings and the last
        one wins (same convention as definition-loader priority).

    Raises:
        No exceptions — malformed files are logged and skipped so
        one bad vendor YAML doesn't crash the app.
    """
    directory = vendors_dir or _VENDORS_DIR
    vendors: dict[str, VendorInfo] = {}

    if not directory.is_dir():
        logger.warning("Vendors directory not found: %s", directory)
        return vendors

    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning(
                    "Skipping vendor file %s: expected a YAML mapping",
                    path.name,
                )
                continue
            vendor = VendorInfo.model_validate(data)
            if vendor.id in vendors:
                logger.warning(
                    "Duplicate vendor_id %r in %s (overrides earlier)",
                    vendor.id,
                    path.name,
                )
            vendors[vendor.id] = vendor
            logger.debug("Loaded vendor %r from %s", vendor.id, path.name)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "CORRUPT VENDOR FILE SKIPPED: %s — %s", path.name, exc
            )

    logger.info("Loaded %d vendor(s) from %s", len(vendors), directory)
    return vendors
