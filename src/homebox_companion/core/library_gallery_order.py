"""Persistent Companion-only photo display order, scoped to a Homebox identity/group/item.

Homebox 0.27 does not expose attachment-position/order in its API. We keep
only attachment IDs here, never image bytes, credentials or item metadata.
Each item uses a separate small atomic file to avoid cross-item write races.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from homebox_companion.homebox.auth import HomeboxAccess

_ORDER_DIR = Path("/app/data/library_gallery_orders")


def _path(access: HomeboxAccess, item_id: str) -> Path:
    # Non-reversible file names prevent leaking source identifiers in directory names.
    data = "\x00".join([access.identity_scope, access.group_id or "", item_id])
    return _ORDER_DIR / (hashlib.sha256(data.encode("utf-8")).hexdigest() + ".json")


def ordered_photo_ids(access: HomeboxAccess, item_id: str, existing: list[str]) -> list[str]:
    """Retain the user-defined ordering, then append any newly uploaded photos."""
    valid = set(existing)
    stored: list[str] = []
    try:
        content = json.loads(_path(access, item_id).read_text(encoding="utf-8"))
        if isinstance(content, list):
            stored = [x for x in content if isinstance(x, str) and x in valid]
    except OSError, ValueError, TypeError:
        pass
    stored = list(dict.fromkeys(stored))
    return stored + [x for x in existing if x not in stored]


def save_photo_order(access: HomeboxAccess, item_id: str, order: list[str]) -> None:
    """Save one user's Companion gallery order, atomically and privately."""
    _ORDER_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = _path(access, item_id)
    descriptor, temporary = tempfile.mkstemp(prefix=".gallery-", dir=_ORDER_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            os.chmod(temporary, 0o600)
            json.dump(order, destination, separators=(",", ":"))
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, filename)
        filename.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)
