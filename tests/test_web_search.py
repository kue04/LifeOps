from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

from tools import web_search


class WebSearchTest(unittest.TestCase):
    def test_auto_uses_bing_before_duckduckgo_timeout(self) -> None:
        bing_result = {
            "provider": "bing",
            "query": "昆明 旅游",
            "results": [{"name": "昆明旅游攻略", "url": "https://example.com/kunming"}],
        }

        with (
            patch("tools.web_search._search_searchfree", side_effect=requests.RequestException("searchfree down")),
            patch("tools.web_search._search_duckduckgo", side_effect=requests.RequestException("duckduckgo timeout")) as duckduckgo,
            patch("tools.web_search._search_bing_rss", return_value=bing_result),
        ):
            result = web_search._search_auto("昆明 旅游", 3)

        self.assertEqual(result["provider"], "bing")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["attempts"][-1], {"provider": "bing", "status": "success"})
        duckduckgo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
