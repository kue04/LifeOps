from __future__ import annotations

import unittest

from services.geocoder import geocode_city
from tools.weather import get_weather


class GeocoderWeatherTest(unittest.TestCase):
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
