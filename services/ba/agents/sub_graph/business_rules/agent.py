"""Business Rules subgraph."""

from __future__ import annotations

from google.adk.workflow import Workflow

from .nodes.discussion.node import create_br_discussion_node
from .nodes.extractor.node import create_br_extractor_node
from .nodes.flags_checker.node import create_br_flags_checker_node


def create_business_rules_pipeline():
    ext = create_br_extractor_node()
    flags = create_br_flags_checker_node()
    disc = create_br_discussion_node()
    return Workflow(
        name="business_rules_workflow",
        edges=[
            ("START", ext),
            (ext, flags),
            (flags, disc),
        ],
    )


# Singleton nodes for stable graph references
_br_extractor = create_br_extractor_node()
_br_flags = create_br_flags_checker_node()
_br_discussion = create_br_discussion_node()

br_subgraph = Workflow(
    name="business_rules_workflow",
    edges=[
        ("START", _br_extractor),
        (_br_extractor, _br_flags),
        (_br_flags, _br_discussion),
    ],
)
