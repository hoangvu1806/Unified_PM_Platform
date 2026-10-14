"""New Feature Agent — compatibility wrapper around the unified BA graph."""

from agents.ba_agent.agent import create_ba_agent

create_new_feature_agent = create_ba_agent

__all__ = ["create_new_feature_agent"]
