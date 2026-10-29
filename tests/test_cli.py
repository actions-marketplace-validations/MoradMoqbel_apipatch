"""
Unit tests for CLI — no LLM required.
"""

import os
import sys
import unittest
import subprocess
import tempfile


class TestCLI(unittest.TestCase):

    def test_cli_version(self):
        res = subprocess.run(
            [sys.executable, "-m", "apipatch.cli", "--version"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        combined = res.stdout.lower() + res.stderr.lower()
        self.assertIn("apipatch", combined)

    def test_cli_no_args_shows_help(self):
        res = subprocess.run(
            [sys.executable, "-m", "apipatch.cli"],
            capture_output=True,
            text=True
        )
        # argparse exits 0 when we call print_help + sys.exit(0)
        self.assertEqual(res.returncode, 0)
        combined = res.stdout + res.stderr
        self.assertIn("scan", combined)
        self.assertIn("fix", combined)

    def test_cli_scan_python_offline(self):
        """Scanning a file without a provider should exit 0 and not crash."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("def add(a, b):\n    return a + b\n")
            temp_path = f.name
        try:
            res = subprocess.run(
                [sys.executable, "-m", "apipatch.cli", "scan", temp_path],
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
        finally:
            os.remove(temp_path)

    def test_cli_scan_js_file_offline(self):
        """Scanning a .js file without a provider should exit 0 and not crash."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as f:
            f.write("const x = require('express');\n")
            temp_path = f.name
        try:
            res = subprocess.run(
                [sys.executable, "-m", "apipatch.cli", "scan", temp_path],
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
        finally:
            os.remove(temp_path)

    def test_cli_detect_command(self):
        """detect command should exit 0 even with an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            res = subprocess.run(
                [sys.executable, "-m", "apipatch.cli", "detect", tmpdir],
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)

    def test_cli_fix_with_verify_tests_flag(self):
        """fix command with --verify-tests should execute cleanly."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write("def add(a, b):\n    return a + b\n")
            temp_path = f.name
        try:
            res = subprocess.run(
                [sys.executable, "-m", "apipatch.cli", "fix", temp_path, "--verify-tests"],
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0)
        finally:
            os.remove(temp_path)

    def test_cli_hunt_help(self):
        """hunt command help should list --submit and --no-fork options."""
        res = subprocess.run(
            [sys.executable, "-m", "apipatch.cli", "hunt", "--help"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        combined = res.stdout + res.stderr
        self.assertIn("--submit", combined)
        self.assertIn("--no-fork", combined)

    def test_cli_pr_help(self):
        """pr command help should list repo, --dry-run, --fork, --token, --path, --title."""
        res = subprocess.run(
            [sys.executable, "-m", "apipatch.cli", "pr", "--help"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        combined = res.stdout + res.stderr
        self.assertIn("repo", combined)
        self.assertIn("--dry-run", combined)
        self.assertIn("--fork", combined)
        self.assertIn("--token", combined)
        self.assertIn("--path", combined)
        self.assertIn("--title", combined)
        self.assertIn("--include-docs", combined)
        self.assertIn("--include-tests", combined)
        self.assertIn("--ignore-docs", combined)
        self.assertIn("--ignore-tests", combined)

    def test_cli_webhook_help(self):
        """webhook command help should list --port, --host, --secret."""
        res = subprocess.run(
            [sys.executable, "-m", "apipatch.cli", "webhook", "--help"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        combined = res.stdout + res.stderr
        self.assertIn("--port", combined)
        self.assertIn("--host", combined)
        self.assertIn("--secret", combined)


if __name__ == "__main__":
    unittest.main()

