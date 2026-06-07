from __future__ import annotations

import unittest

import api


class ApiImportTest(unittest.TestCase):
    def test_fastapi_app_exists(self) -> None:
        self.assertEqual(api.app.title, "LifeOps Agent API")


if __name__ == "__main__":
    unittest.main()

