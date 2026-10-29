"""
Unit tests for Monorepo & Subproject Discovery Engine
"""

import unittest
from apipatch.monorepo import MonorepoManager


class TestMonorepoManager(unittest.TestCase):

    def setUp(self):
        self.sample_paths = [
            # Root files
            "README.md",
            "setup.py",
            # Subproject 1: rag_tutorials
            "rag_tutorials/requirements.txt",
            "rag_tutorials/advanced_rag.py",
            "rag_tutorials/models/embed.py",
            # Subproject 2: agent_teams
            "agent_teams/finance/requirements.txt",
            "agent_teams/finance/agent.py",
            # Subproject 3: web_app
            "web_app/package.json",
            "web_app/src/index.ts",
            # Unrelated docs
            "docs/guide.md"
        ]

    def test_find_nearest_manifest(self):
        manifest_paths = [
            "setup.py",
            "rag_tutorials/requirements.txt",
            "agent_teams/finance/requirements.txt",
            "web_app/package.json"
        ]

        # Nested in rag_tutorials
        m1 = MonorepoManager.find_nearest_manifest("rag_tutorials/models/embed.py", manifest_paths)
        self.assertEqual(m1, "rag_tutorials/requirements.txt")

        # Nested in agent_teams/finance
        m2 = MonorepoManager.find_nearest_manifest("agent_teams/finance/agent.py", manifest_paths)
        self.assertEqual(m2, "agent_teams/finance/requirements.txt")

        # In web_app
        m3 = MonorepoManager.find_nearest_manifest("web_app/src/index.ts", manifest_paths)
        self.assertEqual(m3, "web_app/package.json")

        # Top level file
        m4 = MonorepoManager.find_nearest_manifest("README.md", manifest_paths)
        self.assertEqual(m4, "setup.py")

    def test_discover_subprojects_from_paths(self):
        subprojects = MonorepoManager.discover_subprojects_from_paths(self.sample_paths)

        # Should discover root, rag_tutorials, agent_teams/finance, web_app
        self.assertIn("rag_tutorials", subprojects)
        self.assertIn("agent_teams/finance", subprojects)
        self.assertIn("web_app", subprojects)
        self.assertTrue(MonorepoManager.is_monorepo(subprojects))

        # Check assigned files
        self.assertIn("rag_tutorials/advanced_rag.py", subprojects["rag_tutorials"]["files"])
        self.assertIn("rag_tutorials/models/embed.py", subprojects["rag_tutorials"]["files"])
        self.assertIn("agent_teams/finance/agent.py", subprojects["agent_teams/finance"]["files"])
        self.assertIn("web_app/src/index.ts", subprojects["web_app"]["files"])

    def test_single_project_is_not_monorepo(self):
        flat_paths = [
            "requirements.txt",
            "main.py",
            "utils/helper.py"
        ]
        subprojects = MonorepoManager.discover_subprojects_from_paths(flat_paths)
        self.assertIn("", subprojects)
        self.assertFalse(MonorepoManager.is_monorepo(subprojects))

    def test_resolve_scoped_title(self):
        # All files in rag_tutorials
        files = [
            "rag_tutorials/advanced_rag.py",
            "rag_tutorials/models/embed.py"
        ]
        title, subproject = MonorepoManager.resolve_scoped_title(files, "Migrate legacy LangChain")
        self.assertEqual(subproject, "rag_tutorials")
        self.assertEqual(title, "[Rag_tutorials] [ApiPatch] Migrate legacy LangChain")

        # Mixed files across subprojects -> no subproject prefix
        mixed_files = [
            "rag_tutorials/advanced_rag.py",
            "web_app/src/index.ts"
        ]
        title_mixed, subproject_mixed = MonorepoManager.resolve_scoped_title(mixed_files, "Migrate code")
        self.assertIsNone(subproject_mixed)
        self.assertEqual(title_mixed, "Migrate code")

    def test_partition_audit_by_subproject(self):
        subprojects = MonorepoManager.discover_subprojects_from_paths(self.sample_paths)
        audit_results = [
            {"file": "rag_tutorials/advanced_rag.py", "issues": ["dep1"]},
            {"file": "rag_tutorials/models/embed.py", "issues": ["dep2"]},
            {"file": "web_app/src/index.ts", "issues": ["dep3"]},
        ]
        partitions = MonorepoManager.partition_audit_by_subproject(audit_results, subprojects)
        self.assertIn("rag_tutorials", partitions)
        self.assertIn("web_app", partitions)
        self.assertEqual(len(partitions["rag_tutorials"]), 2)
        self.assertEqual(len(partitions["web_app"]), 1)


    def test_discover_subprojects_ignores_docs_and_tests(self):
        paths_with_docs = [
            "core/pyproject.toml",
            "core/main.py",
            "docs/package.json",
            "docs/index.md",
            "tests/pyproject.toml",
            "tests/test_main.py",
        ]
        # By default, docs and tests are ignored
        subprojects = MonorepoManager.discover_subprojects_from_paths(paths_with_docs, ignore_docs=True, ignore_tests=True)
        self.assertIn("core", subprojects)
        self.assertNotIn("docs", subprojects)
        self.assertNotIn("tests", subprojects)

        # When include docs and tests
        subprojects_all = MonorepoManager.discover_subprojects_from_paths(paths_with_docs, ignore_docs=False, ignore_tests=False)
        self.assertIn("core", subprojects_all)
        self.assertIn("docs", subprojects_all)
        self.assertIn("tests", subprojects_all)


if __name__ == "__main__":
    unittest.main()


