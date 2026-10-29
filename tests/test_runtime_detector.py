"""
Unit tests for apipatch.runtime_detector (Target Runtime & CI/CD Context Awareness)
"""

import os
import tempfile
import json
import unittest
from apipatch.runtime_detector import TargetRuntimeDetector, TargetRuntimeContext


class TestRuntimeDetector(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_detect_github_actions_workflow_matrix(self):
        wf_dir = os.path.join(self.project_dir, ".github", "workflows")
        os.makedirs(wf_dir, exist_ok=True)
        wf_file = os.path.join(wf_dir, "test.yml")
        with open(wf_file, "w", encoding="utf-8") as f:
            f.write("""
name: CI
on: [push, pull_request]
jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
        node-version: ["18.x", "20.x"]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
""")

        ctx = TargetRuntimeDetector.detect_from_directory(self.project_dir)
        self.assertTrue(ctx.has_constraints)
        self.assertIn("3.10", ctx.python_versions)
        self.assertIn("3.11", ctx.python_versions)
        self.assertIn("3.12", ctx.python_versions)
        self.assertIn("18.x", ctx.node_versions)
        self.assertIn("20.x", ctx.node_versions)
        self.assertIn(".github/workflows/test.yml", ctx.ci_workflow_files)

        prompt_ctx = ctx.to_prompt_context()
        self.assertIn("TARGET RUNTIME & CI/CD MATRIX CONSTRAINTS", prompt_ctx)
        self.assertIn("Python Target Version(s): 3.10, 3.11, 3.12", prompt_ctx)
        self.assertIn("CRITICAL COMPATIBILITY: The project pins Python <= 3.12", prompt_ctx)
        self.assertIn("Do NOT introduce Python 3.13+ features", prompt_ctx)

    def test_detect_pyproject_toml_pins(self):
        pyproject_file = os.path.join(self.project_dir, "pyproject.toml")
        with open(pyproject_file, "w", encoding="utf-8") as f:
            f.write("""
[project]
name = "enterprise-service"
version = "1.0.0"
requires-python = ">=3.10,<3.13"

[tool.ruff]
target-version = "py312"
""")

        ctx = TargetRuntimeDetector.detect_from_directory(self.project_dir)
        self.assertTrue(ctx.has_constraints)
        self.assertIn(">=3.10,<3.13", ctx.python_versions)
        self.assertIn("3.12", ctx.python_versions)
        self.assertIn("pyproject.toml", ctx.pinned_sources)

    def test_detect_dockerfile_and_python_version_file(self):
        dockerfile = os.path.join(self.project_dir, "Dockerfile")
        with open(dockerfile, "w", encoding="utf-8") as f:
            f.write("""
FROM python:3.12-slim
WORKDIR /app
COPY . .
""")

        pver_file = os.path.join(self.project_dir, ".python-version")
        with open(pver_file, "w", encoding="utf-8") as f:
            f.write("3.12.4\n")

        ctx = TargetRuntimeDetector.detect_from_directory(self.project_dir)
        self.assertIn("3.12", ctx.python_versions)
        self.assertIn("3.12.4", ctx.python_versions)
        self.assertIn("Dockerfile", ctx.pinned_sources)
        self.assertIn(".python-version", ctx.pinned_sources)

    def test_detect_package_json_and_nvmrc(self):
        pkg_json = os.path.join(self.project_dir, "package.json")
        with open(pkg_json, "w", encoding="utf-8") as f:
            json.dump({
                "name": "my-app",
                "engines": {
                    "node": ">=18.0.0"
                }
            }, f)

        nvmrc = os.path.join(self.project_dir, ".nvmrc")
        with open(nvmrc, "w", encoding="utf-8") as f:
            f.write("v20.11.0\n")

        ctx = TargetRuntimeDetector.detect_from_directory(self.project_dir)
        self.assertIn(">=18.0.0", ctx.node_versions)
        self.assertIn("20.11.0", ctx.node_versions)
        prompt_ctx = ctx.to_prompt_context()
        self.assertIn("Node.js Target Version(s)", prompt_ctx)

    def test_detect_from_file_map(self):
        file_map = {
            ".github/workflows/ci.yml": "jobs:\n  test:\n    strategy:\n      matrix:\n        python-version: [3.11, 3.12]",
            "Dockerfile": "FROM node:20-alpine\nRUN echo ok",
            "setup.cfg": "[options]\npython_requires = >=3.10"
        }
        ctx = TargetRuntimeDetector.detect_from_file_map(file_map)
        self.assertTrue(ctx.has_constraints)
        self.assertIn("3.11", ctx.python_versions)
        self.assertIn("3.12", ctx.python_versions)
        self.assertIn(">=3.10", ctx.python_versions)
        self.assertIn("20", ctx.node_versions)


if __name__ == "__main__":
    unittest.main()
