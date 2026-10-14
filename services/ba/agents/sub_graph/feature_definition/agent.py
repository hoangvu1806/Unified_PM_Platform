"""Feature Definition ADK Subgraph Workflow Agent.

Exports `fd_subgraph` and canonical `agent` instance compatible with ADK CLI (`adk run`, `adk web`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.adk.workflow import JoinNode, Workflow

# Ensure project root directory is in sys.path when loaded via ADK CLI (adk run/web)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .nodes import (
    create_fd_discussion_node,
    create_fd_extractor_node,
    create_fd_flags_checker_node,
    create_oq_asm_detector_node,
)

join_node = JoinNode(name="fd_fan_in_join")


def create_feature_definition_pipeline(db_repository=None):
    """Factory function for backward compatibility with server.py."""
    fd_discussion_node = create_fd_discussion_node()
    fd_extractor_node = create_fd_extractor_node()
    fd_flags_checker_node = create_fd_flags_checker_node()
    oq_asm_detector_node = create_oq_asm_detector_node()

    # Define ADK Parallel Fan-Out / Fan-In Workflow Edges
    return Workflow(
        name="feature_definition_workflow",
        edges=[
            # 1. Fan-Out song song ngay từ START: Extractor và OQ/ASM Detector
            ("START", (fd_extractor_node, oq_asm_detector_node)),
            # 2. Nhánh 1: Extractor -> Flags Checker
            (fd_extractor_node, fd_flags_checker_node),
            # 3. Fan-In: Gom cả 2 nhánh (Flags Checker & OQ/ASM Detector) vào JoinNode
            ((fd_flags_checker_node, oq_asm_detector_node), join_node),
            # 4. Tiếp tục sang Discussion Agent
            (join_node, fd_discussion_node),
        ],
    )


# Export `root_agent`, `fd_subgraph`, and `agent` as standard entrypoints for ADK CLI & BA router
root_agent = create_feature_definition_pipeline()
fd_subgraph = root_agent
agent = root_agent

__all__ = [
    "agent",
    "create_feature_definition_pipeline",
    "fd_subgraph",
    "root_agent",
]
