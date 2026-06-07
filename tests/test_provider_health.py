from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from api import app


class ProviderHealthTest(unittest.TestCase):
    def test_provider_health_contract(self) -> None:
        response = TestClient(app).get("/health/providers")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        providers = data["providers"]
        names = {item["name"] for item in providers}
        statuses = {item["status"] for item in providers}

        self.assertEqual(data["status"], "ok")
        self.assertEqual(names, {"llm", "weather", "place", "search", "route"})
        self.assertLessEqual(statuses, {"ok", "degraded", "unconfigured"})
        for item in providers:
            self.assertIn("provider", item)
            self.assertIn("configured", item)
            self.assertIn("message", item)


if __name__ == "__main__":
    unittest.main()
