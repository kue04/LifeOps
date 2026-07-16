from __future__ import annotations

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

import requests

from tools import web_search


class WebSearchTest(unittest.TestCase):
    def test_bing_uses_curl_when_requests_times_out(self) -> None:
        original_provider = web_search.settings.search_provider
        object.__setattr__(web_search.settings, "search_provider", "bing")
        rss = """<?xml version="1.0" encoding="utf-8"?>
        <rss><channel><item><title>杭州旅游攻略</title><link>https://example.com/hangzhou</link>
        <description>西湖门票与开放时间</description></item></channel></rss>"""

        try:
            with (
                patch("tools.web_search.requests.get", side_effect=requests.Timeout("slow")),
                patch("subprocess.run", return_value=CompletedProcess([], 0, rss, "")) as curl_run,
                patch("shutil.which", return_value="curl.exe"),
            ):
                result = web_search.search_web("杭州旅游", 3)
        finally:
            object.__setattr__(web_search.settings, "search_provider", original_provider)

        self.assertEqual(result["provider"], "bing")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["name"], "杭州旅游攻略")
        self.assertEqual(curl_run.call_count, 1)

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
