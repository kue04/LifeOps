from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

import tools.places as places


class AmapPlaceSearchTest(unittest.TestCase):
    def test_amap_returns_partial_places_when_later_keyword_times_out(self) -> None:
        original_key = places.settings.amap_api_key
        object.__setattr__(places.settings, "amap_api_key", "test-key")

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "status": "1",
                    "pois": [
                        {"name": "洛阳博物馆", "address": "聂泰路", "adname": "洛龙区", "type": "科教文化服务;博物馆", "location": "112.435,34.618"},
                        {"name": "龙门石窟", "address": "龙门大道", "adname": "洛龙区", "type": "风景名胜", "location": "112.479,34.559"},
                    ],
                }

        try:
            with (
                patch("tools.places.requests.get", side_effect=[Response(), requests.Timeout("slow")]) as mocked,
                patch("tools.places.shutil.which", return_value=None),
            ):
                result = places._search_amap("洛阳", ["博物馆", "夜景", "咖啡"])
        finally:
            object.__setattr__(places.settings, "amap_api_key", original_key)

        self.assertEqual([item["name"] for item in result], ["洛阳博物馆", "龙门石窟"])
        self.assertTrue(all(item["provider"] == "amap" for item in result))
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
