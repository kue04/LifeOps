from __future__ import annotations

import unittest
from uuid import uuid4

from api import _frontend_response
from storage.db import connect, get_profile, save_plan_feedback, save_task_history


class FeedbackProfileTest(unittest.TestCase):
    def test_feedback_updates_profile_memory(self) -> None:
        marker = f"测试地点{uuid4().hex[:6]}"
        task_id = save_task_history(
            f"周末去杭州玩，喜欢 {marker}",
            {"title": "测试计划", "itinerary": [{"place": marker}]},
        )
        with connect() as conn:
            original_profile = conn.execute("SELECT likes, dislikes, pace, budget_style FROM user_profile WHERE user_id = ?", ("default",)).fetchone()
        try:
            result = save_plan_feedback(
                {
                    "task_id": task_id,
                    "trace_id": task_id,
                    "rating": 5,
                    "tags": ["喜欢", "路线顺"],
                    "note": "路线舒服",
                    "item_feedback": [{"place": marker, "sentiment": "like"}],
                }
            )
            profile = get_profile()

            self.assertTrue(result["learned_preferences"])
            self.assertIn(marker, profile["profile"]["likes"])
            self.assertGreaterEqual(profile["stats"]["feedback_count"], 1)
            self.assertTrue(any(item["content"] == marker for item in profile["recent_memory"]))
        finally:
            with connect() as conn:
                conn.execute("DELETE FROM memory_events WHERE source_task_id = ? OR source_trace_id = ?", (task_id, task_id))
                conn.execute("DELETE FROM plan_feedback WHERE task_id = ? OR trace_id = ?", (task_id, task_id))
                conn.execute("DELETE FROM task_history WHERE task_id = ?", (task_id,))
                if original_profile:
                    conn.execute(
                        "UPDATE user_profile SET likes = ?, dislikes = ?, pace = ?, budget_style = ? WHERE user_id = ?",
                        (
                            original_profile["likes"],
                            original_profile["dislikes"],
                            original_profile["pace"],
                            original_profile["budget_style"],
                            "default",
                        ),
                    )

    def test_frontend_response_includes_quality_score(self) -> None:
        result = _frontend_response(
            {
                "status": "success",
                "constraints": {"preferences": ["咖啡"], "budget": 300},
                "final_plan": {
                    "title": "杭州半日",
                    "weather": "晴",
                    "travel_research": {"sources": [{"title": "来源", "url": "https://example.com", "content": "咖啡"}]},
                    "itinerary": [{"time": "10:00", "place": "咖啡店", "cost": 30, "cost_known": True, "evidence": ["来源"]}],
                    "budget": {"total": 120, "budget_limit": 300, "unknown_activity_cost_items": []},
                    "fallbacks": ["下雨改室内"],
                },
                "reflection": {"passed": True, "next_action": "final"},
            }
        )

        self.assertIn("quality_score", result)
        self.assertGreaterEqual(result["quality_score"]["overall"], 70)
        self.assertEqual(len(result["quality_score"]["dimensions"]), 6)


if __name__ == "__main__":
    unittest.main()
