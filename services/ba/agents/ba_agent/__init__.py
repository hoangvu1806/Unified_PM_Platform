"""BA Agent package — one unified graph for all ticket types."""

from __future__ import annotations

__all__ = ["create_ba_agent", "create_new_feature_agent", "root_agent"]


def __getattr__(name: str):
    if name in __all__:
        from .agent import create_ba_agent, create_new_feature_agent, root_agent

        return {
            "create_ba_agent": create_ba_agent,
            "create_new_feature_agent": create_new_feature_agent,
            "root_agent": root_agent,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
