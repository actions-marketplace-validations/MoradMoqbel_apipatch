"""
Unit tests for ApiPatch Radar subsystem and Web Dashboard server.
"""

import os
import sys
import json
import unittest
import subprocess
from unittest.mock import patch, MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from radar_server import (
    fetch_github_api,
    _SEARCH_CACHE,
    VERIFIED_SEPT_2026_LEADS,
    SYSTEM_DATE
)


class TestRadarSubsystem(unittest.TestCase):

    def setUp(self):
        _SEARCH_CACHE.clear()

    def test_cli_radar_subcommand_registered(self):
        """Ensure 'radar' command is properly configured and shows help."""
        res = subprocess.run(
            [sys.executable, "-m", "apipatch", "radar", "--help"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--port", res.stdout)
        self.assertIn("--no-browser", res.stdout)

    def test_system_date_integrity(self):
        """Ensure radar server uses the simulated 2026-09-13 baseline date."""
        self.assertEqual(SYSTEM_DATE, "2026-09-13")

    def test_verified_leads_structure(self):
        """Verify fallback leads have valid PR metadata and executable commands."""
        self.assertGreater(len(VERIFIED_SEPT_2026_LEADS), 0)
        for lead in VERIFIED_SEPT_2026_LEADS:
            self.assertIn("title", lead)
            self.assertIn("url", lead)
            self.assertIn("repo", lead)
            self.assertTrue(lead["url"].startswith("https://github.com/"))
            self.assertTrue(lead["apipatch_cmd"].startswith("python -m apipatch pr "))

    @patch("urllib.request.urlopen")
    def test_fetch_github_api_caching(self, mock_urlopen):
        """Verify search API results are cached and don't re-query unnecessarily."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"items": [{"id": 1}]}).encode("utf-8")
        mock_resp.headers = {"X-RateLimit-Limit": "5000", "X-RateLimit-Remaining": "4999"}
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # First call hits mock
        res1 = fetch_github_api("https://api.github.com/test_endpoint")
        self.assertEqual(res1["status"], 200)
        self.assertEqual(mock_urlopen.call_count, 1)

        # Second call hits cache
        res2 = fetch_github_api("https://api.github.com/test_endpoint")
        self.assertEqual(res2["status"], 200)
        self.assertEqual(mock_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
