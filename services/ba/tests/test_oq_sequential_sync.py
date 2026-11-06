"""Regression coverage for one-at-a-time OQ synchronization inputs."""

from __future__ import annotations

import unittest

from agents.ba_agent.open_questions import format_open_questions_reply
from agents.sub_graph.feature_definition.nodes.oq_asm_detector.callback import (
    apply_oq_resolutions,
    ensure_oq_sync_queue,
    resolutions_from_user_message,
)


def _state() -> dict:
    return {
        "current_turn": 7,
        "open_questions": [
            {"id": f"OQ-{index:03}", "question": f"Question {index}", "status": "open"}
            for index in range(1, 4)
        ],
        "artifacts": {},
    }


class SequentialOpenQuestionInputTests(unittest.TestCase):
    def test_three_answers_are_queued_as_three_independent_items(self) -> None:
        state = _state()
        answers = resolutions_from_user_message(
            "OQ-001: Use existing account.\n"
            "OQ-002: Require at least 10 characters.\n"
            "OQ-003: OTP expires after five minutes."
        )

        self.assertEqual(apply_oq_resolutions(state, answers), 3)
        queue = ensure_oq_sync_queue(state)
        self.assertEqual([item["id"] for item in queue], ["OQ-001", "OQ-002", "OQ-003"])
        self.assertEqual(
            [item["sync_status"] for item in state["open_questions"]],
            ["pending", "pending", "pending"],
        )

    def test_single_answer_keeps_other_questions_open_for_follow_up(self) -> None:
        state = _state()
        answers = resolutions_from_user_message("OQ-002: Require at least 10 characters.")

        self.assertEqual(apply_oq_resolutions(state, answers), 1)
        queue = ensure_oq_sync_queue(state)
        self.assertEqual([item["id"] for item in queue], ["OQ-002"])
        reply = format_open_questions_reply(state)
        self.assertIn("OQ-001", reply)
        self.assertIn("OQ-003", reply)


if __name__ == "__main__":
    unittest.main()
