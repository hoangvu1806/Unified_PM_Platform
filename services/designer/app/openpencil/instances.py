"""Which OpenPencil instance a designer uses (refactor-plan/06).

Order: the user's row in ``designer.openpencil_instances`` → the default
instance from ``.env``. In ``PLATFORM_ENV=dev`` an endpoint typed in the
Designer settings still wins unless it is a loopback address, which inside a
container never points at the user's OpenPencil.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from ..core.config import Settings

LOOPBACK = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# endpoint -> MCP bearer token of a registered instance
_tokens: dict[str, str] = {}


@dataclass(frozen=True)
class Instance:
    mcp_url: str
    editor_url: str
    source: str  # "user" | "default" | "requested"


def token_for(endpoint: str) -> str:
    return _tokens.get(endpoint.strip(), "")


async def resolve_instance(store, settings: Settings, user_id: str | None) -> Instance:
    if user_id:
        row = await store.get_openpencil_instance(user_id)
        if row:
            if row.get("auth_token"):
                _tokens[row["mcp_url"].strip()] = row["auth_token"]
            return Instance(row["mcp_url"], row["editor_url"], "user")
    return Instance(settings.openpencil_default_mcp_url, settings.openpencil_default_editor_url, "default")


async def resolve_endpoint(store, settings: Settings, user_id: str | None, requested: str | None) -> str:
    instance = await resolve_instance(store, settings, user_id)
    if instance.source == "user":
        return instance.mcp_url
    if settings.platform_env == "dev" and requested:
        host = (urlsplit(requested.strip()).hostname or "").lower()
        if host and host not in LOOPBACK:
            return requested.strip()
    return instance.mcp_url
