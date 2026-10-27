"""Images users upload (chat attachments, BA handoff), stored per project under ``layout.asset_key``.

Screens reference them as ``asset:<id>``; ids are content-addressed, so an object is never rewritten
with different bytes.
"""

from __future__ import annotations

from . import layout


def _storage():
    from platform_core.storage import get_storage

    return get_storage()


def save_asset(project_id: str | None, asset_id: str, data: bytes) -> str:
    key = layout.asset_key(project_id, asset_id)
    _storage().put(key, data)
    return key


def read_asset(project_id: str | None, asset_id: str) -> bytes | None:
    """The asset's bytes, or None. Falls back to the unscoped key used before assets were per project."""
    storage = _storage()
    for key in dict.fromkeys((layout.asset_key(project_id, asset_id), layout.legacy_asset_key(asset_id))):
        if storage.exists(key):
            return storage.get(key)
    return None
