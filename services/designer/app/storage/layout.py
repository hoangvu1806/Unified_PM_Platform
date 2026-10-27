"""Storage keys of the Designer — the only place that decides where its files live.

    projects/<project>/designer/
      sessions/<session>/screens/<screen>/v0001.html   screen HTML, one immutable object per version
      assets/<asset>                                   images users upload (chat, BA handoff)
      design-systems/<design_system>/source.fig        imported Figma file
      outputs/<run>/r<revision>-<file>                 published deliverables (project Assets)

Session data lives under the session (removed with it); deliverables do not, because the
project's Assets keep referencing them. Without a project (auth disabled, local tools) the same
tree lives under ``shared/designer/``.
"""

from __future__ import annotations

from platform_core.storage import project_key

MODULE = "designer"


def _key(project_id: str | None, *parts: str) -> str:
    return project_key(project_id or None, MODULE, *parts)


def session_prefix(project_id: str | None, session_id: str) -> str:
    return _key(project_id, "sessions", str(session_id)) + "/"


def screen_version_key(project_id: str | None, session_id: str, screen_id: str, version: int) -> str:
    return _key(project_id, "sessions", str(session_id), "screens", screen_id, f"v{version:04d}.html")


def asset_key(project_id: str | None, asset_id: str) -> str:
    return _key(project_id, "assets", asset_id)


def legacy_asset_key(asset_id: str) -> str:
    """Uploads stored before assets were project-scoped."""
    return project_key(None, MODULE, "assets", asset_id)


def design_system_prefix(project_id: str | None, ds_id: str) -> str:
    return _key(project_id, "design-systems", ds_id) + "/"


def design_system_source_key(project_id: str | None, ds_id: str) -> str:
    return _key(project_id, "design-systems", ds_id, "source.fig")


def output_key(project_id: str | None, run_id: str, filename: str) -> str:
    return _key(project_id, "outputs", str(run_id), filename)
