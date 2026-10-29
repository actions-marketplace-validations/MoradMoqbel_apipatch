"""
Unit tests for build_project_context
"""

import os
import unittest
import tempfile
import json
from apipatch.auto_detector import build_project_context


class TestProjectContext(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.test_dir.cleanup()

    def test_build_context_with_requirements_and_frameworks(self):
        req_file = os.path.join(self.test_dir.name, "requirements.txt")
        with open(req_file, "w", encoding="utf-8") as f:
            f.write("fastapi>=0.100.0\npydantic>=2.0.0\nopenai==1.10.0\n")

        main_py = os.path.join(self.test_dir.name, "main.py")
        with open(main_py, "w", encoding="utf-8") as f:
            f.write("from fastapi import FastAPI\napp = FastAPI()\n")

        context = build_project_context(self.test_dir.name)
        self.assertIn("FastAPI", context)
        self.assertIn("Pydantic", context)
        self.assertIn("OpenAI SDK", context)
        self.assertIn("fastapi", context.lower())
        self.assertIn("main.py", context)

    def test_build_context_with_package_json(self):
        pkg_file = os.path.join(self.test_dir.name, "package.json")
        with open(pkg_file, "w", encoding="utf-8") as f:
            json.dump({
                "dependencies": {
                    "react": "^18.2.0",
                    "next": "^14.0.0",
                    "@supabase/supabase-js": "^2.39.0"
                }
            }, f)

        context = build_project_context(self.test_dir.name)
        self.assertIn("React", context)
        self.assertIn("Next.js", context)
        self.assertIn("@supabase/supabase-js", context)

    def test_build_context_with_ci_runtime_matrix(self):
        wf_dir = os.path.join(self.test_dir.name, ".github", "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        with open(os.path.join(wf_dir, "ci.yml"), "w", encoding="utf-8") as f:
            f.write("jobs:\n  build:\n    strategy:\n      matrix:\n        python-version: ['3.11', '3.12']\n")

        context = build_project_context(self.test_dir.name)
        self.assertIn("TARGET RUNTIME & CI/CD MATRIX CONSTRAINTS", context)
        self.assertIn("3.11, 3.12", context)
        self.assertIn("Python <= 3.12", context)


if __name__ == "__main__":
    unittest.main()

