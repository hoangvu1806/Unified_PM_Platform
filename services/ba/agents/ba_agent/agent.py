"""BA Agent — unified ADK Workflow."""

from __future__ import annotations

import sys
from pathlib import Path

from google.adk.workflow import Workflow

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.ba_agent.constants import (
    ROUTE_BR,
    ROUTE_FD,
    ROUTE_LOCKED,
    ROUTE_STUB,
    ROUTE_UC,
    ROUTE_VALIDATE,
    ROUTE_WF,
)
from agents.ba_agent.nodes import ba_not_ready_node, ba_section_locked_node
from agents.ba_agent.router import ba_router_node
from agents.sub_graph.business_rules.agent import br_subgraph
from agents.sub_graph.feature_definition.agent import fd_subgraph
from agents.sub_graph.use_cases.agent import uc_subgraph
from agents.sub_graph.validation_agent.agent import va_subgraph
from agents.sub_graph.workflow.agent import wf_subgraph


def create_ba_agent() -> Workflow:
    """Build the unified BA Agent workflow."""
    return Workflow(
        name="ba_agent",
        edges=[
            ("START", ba_router_node),
            (
                ba_router_node,
                {
                    ROUTE_FD: fd_subgraph,
                    ROUTE_BR: br_subgraph,
                    ROUTE_WF: wf_subgraph,
                    ROUTE_UC: uc_subgraph,
                    ROUTE_VALIDATE: va_subgraph,
                    ROUTE_LOCKED: ba_section_locked_node,
                    ROUTE_STUB: ba_not_ready_node,
                },
            ),
        ],
    )


create_new_feature_agent = create_ba_agent
root_agent = create_ba_agent()
agent = root_agent
