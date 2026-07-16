from __future__ import annotations

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

import requests

from services.geocoder import geocode_city
import tools.weather as weather_module
from tools.weather import get_weather


class GeocoderWeatherTest(unittest.TestCase):
    def test_amap_weather_uses_curl_when_requests_ssl_fails(self) -> None:
        original_provider = weather_module.settings.weather_provider
        original_key = weather_module.settings.amap_api_key
        object.__setattr__(weather_module.settings, "weather_provider", "amap")
        object.__setattr__(weather_module.settings, "amap_api_key", "test-key")
        curl_results = [
            CompletedProcess([], 0, '{"status":"1","geocodes":[{"adcode":"330100"}]}', ""),
            CompletedProcess([], 0, '{"status":"1","lives":[{"weather":"晴","temperature":"31"}]}', ""),
        ]

        try:
            with (
                patch("tools.weather.requests.get", side_effect=requests.exceptions.SSLError("ssl")),
                patch("subprocess.run", side_effect=curl_results) as curl_run,
                patch("shutil.which", return_value="curl.exe"),
            ):
                result = get_weather("杭州", "2026-07-18")
        finally:
            object.__setattr__(weather_module.settings, "weather_provider", original_provider)
            object.__setattr__(weather_module.settings, "amap_api_key", original_key)

        self.assertEqual(result["provider"], "amap")
        self.assertEqual(result["temperature"], "31C")
        self.assertEqual(curl_run.call_count, 2)

    def test_xiamen_seed_geocode(self) -> None:
        location = geocode_city("厦门")

        self.assertEqual(location["name"], "厦门")
        self.assertAlmostEqual(location["latitude"], 24.4798, places=3)

    def test_openmeteo_weather_for_xiamen_does_not_crash(self) -> None:
        weather = get_weather("厦门", "2026-05-30")

        self.assertEqual(weather["city"], "厦门")
        self.assertIn("provider", weather)


if __name__ == "__main__":
    unittest.main()
