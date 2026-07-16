from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

import api
from storage.db import connect, record_app_audit, save_app_run_context, save_task_history


class AppContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api.app)

    def test_app_me_uses_normal_user_role(self) -> None:
        result = self.client.get(
            "/app/me",
            headers={"X-User-Id": "alice", "X-User-Role": "operator_admin", "X-User-Name": "Alice"},
        ).json()

        self.assertEqual(result["user_id"], "alice")
        self.assertEqual(result["role"], "operator_admin")
        self.assertFalse(any("knowledge" in key for key in result))
        self.assertNotIn("team_id", result)

    def test_frontend_response_includes_standard_app_contract(self) -> None:
        result = api._frontend_response(
            {
                "status": "success",
                "trace_id": "contract_trace",
                "constraints": {"budget": 300},
                "tool_results": [{"tool_name": "weather_tool", "data": {"condition": "晴"}}],
                "final_plan": {
                    "title": "杭州半日",
                    "goal": "轻松出行",
                    "date": "2026-07-06",
                    "itinerary": [{"time": "10:00-11:00", "place": "西湖", "cost": 0, "cost_known": True}],
                    "budget": {"total": 120, "budget_limit": 300},
                    "travel_research": {"sources": [{"title": "来源", "url": "https://example.com", "content": "参考"}]},
                    "risks": ["雨天注意备选"],
                },
            }
        )

        self.assertEqual(result["task_summary"], "轻松出行")
        self.assertEqual(result["plan"][0]["action"], "西湖")
        self.assertIn("预计总计", result["budget_summary"])
        self.assertTrue(result["tool_sources"])
        self.assertEqual(result["risks"][0]["level"], "medium")

    def test_user_history_is_isolated(self) -> None:
        task_a = save_task_history("isolation user a", {"title": "A"}, user_id="user_a")
        task_b = save_task_history("isolation user b", {"title": "B"}, user_id="user_b")
        save_app_run_context("trace_user_a", "user_a", "user", task_id=task_a, status="success")
        save_app_run_context("trace_user_b", "user_b", "user", task_id=task_b, status="success")
        try:
            response = self.client.get("/app/history", headers={"X-User-Id": "user_a"})
            ids = {item["task_id"] for item in response.json()["items"]}

            self.assertIn(task_a, ids)
            self.assertNotIn(task_b, ids)
        finally:
            with connect() as conn:
                conn.execute("DELETE FROM app_run_context WHERE trace_id IN (?, ?)", ("trace_user_a", "trace_user_b"))
                conn.execute("DELETE FROM task_history WHERE task_id IN (?, ?)", (task_a, task_b))

    def test_calendar_export_requires_confirmation(self) -> None:
        plan = {
            "title": "日历确认测试",
            "date": "2026-07-06",
            "itinerary": [{"time": "10:00-11:00", "place": "西湖"}],
        }

        denied = self.client.post("/app/calendar/ics", headers={"X-User-Id": "calendar_user"}, json={"final_plan": plan})
        self.assertEqual(denied.status_code, 403)

        confirmation_id = None
        try:
            confirmed = self.client.post(
                "/app/confirm-action",
                headers={"X-User-Id": "calendar_user"},
                json={"action_type": "export_calendar", "items": []},
            ).json()
            confirmation_id = confirmed["confirmation_id"]
            exported = self.client.post(
                "/app/calendar/ics",
                headers={"X-User-Id": "calendar_user"},
                json={"final_plan": plan, "confirmation_id": confirmation_id},
            )

            self.assertEqual(exported.status_code, 200)
            self.assertIn("BEGIN:VCALENDAR", exported.text)
        finally:
            if confirmation_id:
                with connect() as conn:
                    conn.execute("DELETE FROM app_confirmations WHERE confirmation_id = ?", (confirmation_id,))
                    conn.execute("DELETE FROM app_audit_log WHERE resource_id = ? OR details LIKE ?", (confirmation_id, f"%{confirmation_id}%"))

    def test_audit_log_requires_operator_admin(self) -> None:
        audit = record_app_audit("audit_actor", "operator_admin", "audit_test", "test", "audit_resource")
        try:
            denied = self.client.get("/app/audit", headers={"X-User-Id": "normal_user"})
            allowed = self.client.get(
                "/app/audit",
                headers={"X-User-Id": "ops", "X-User-Role": "operator_admin"},
            )

            self.assertEqual(denied.status_code, 403)
            self.assertEqual(allowed.status_code, 200)
            self.assertTrue(any(item["audit_id"] == audit["audit_id"] for item in allowed.json()["items"]))
        finally:
            with connect() as conn:
                conn.execute("DELETE FROM app_audit_log WHERE audit_id = ?", (audit["audit_id"],))


if __name__ == "__main__":
    unittest.main()
