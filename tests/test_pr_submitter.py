"""
Unit tests for GitHubPRHunter live PR automation and REST API operations
"""

import unittest
from unittest.mock import patch, MagicMock
from apipatch.proactive_hunter import GitHubPRHunter, _build_raw_url


class TestPRSubmitter(unittest.TestCase):
    def test_build_raw_url_with_html_url(self):
        item = {
            "html_url": "https://github.com/openai/openai-python/blob/main/src/openai/client.py"
        }
        url = _build_raw_url(item)
        self.assertEqual(url, "https://raw.githubusercontent.com/openai/openai-python/main/src/openai/client.py")

    def test_build_raw_url_with_raw_url(self):
        item = {
            "raw_url": "https://raw.githubusercontent.com/custom/repo/v1/main.py"
        }
        self.assertEqual(_build_raw_url(item), "https://raw.githubusercontent.com/custom/repo/v1/main.py")

    def test_generate_pr_payload(self):
        hunter = GitHubPRHunter(github_token="fake_token")
        audit_result = {
            "issues": [{
                "library": "openai",
                "deprecated_symbol": "openai.ChatCompletion.create()",
                "replacement_symbol": "client.chat.completions.create()",
                "description": "Upgrade to OpenAI Python v1 SDK"
            }]
        }
        payload = hunter.generate_pr_payload("owner/repo", "services/ai.py", audit_result)
        self.assertIn("[ApiPatch] Migrate deprecated openai API calls in ai.py", payload["title"])
        self.assertIn("Automated API Migration by [ApiPatch]", payload["body"])
        self.assertIn("openai.ChatCompletion.create()", payload["body"])

    @patch.object(GitHubPRHunter, "_request")
    def test_get_authenticated_user(self, mock_request):
        mock_request.return_value = {"login": "apipatch-bot", "id": 12345}
        hunter = GitHubPRHunter(github_token="valid_token")
        user = hunter.get_authenticated_user()
        self.assertEqual(user, "apipatch-bot")
        mock_request.assert_called_with("/user")

    @patch.object(GitHubPRHunter, "_request")
    def test_get_default_branch(self, mock_request):
        mock_request.return_value = {"default_branch": "develop"}
        hunter = GitHubPRHunter(github_token="valid_token")
        branch = hunter.get_default_branch("test-org/repo")
        self.assertEqual(branch, "develop")

    @patch.object(GitHubPRHunter, "_request")
    def test_create_branch(self, mock_request):
        mock_request.return_value = {"ref": "refs/heads/apipatch/migrate-123"}
        hunter = GitHubPRHunter(github_token="valid_token")
        success = hunter.create_branch("owner/repo", "apipatch/migrate-123", "abcdef123456")
        self.assertTrue(success)

    @patch.object(GitHubPRHunter, "_request")
    def test_submit_pull_request(self, mock_request):
        mock_request.return_value = {
            "html_url": "https://github.com/owner/repo/pull/42",
            "number": 42
        }
        hunter = GitHubPRHunter(github_token="valid_token")
        res = hunter.submit_pull_request(
            base_repo="owner/repo",
            head_branch="myuser:apipatch/migrate-1",
            base_branch="main",
            title="[ApiPatch] Migrate openai",
            body="PR Description"
        )
    def test_generate_pr_markdown_with_custom_title_and_scope_prefix(self):
        from apipatch.github_client import GitHubClient
        audit_results = [{
            "file": "apps/beifong/models/schemas.py",
            "detected_issues": [{
                "library": "pydantic",
                "deprecated_symbol": "class Config",
                "replacement_symbol": "model_config = ConfigDict()"
            }]
        }]
        
        # Test default with scope prefix
        payload_scope = GitHubClient.generate_pr_markdown("owner/repo", audit_results, scope_prefix="[Beifong] ")
        self.assertEqual(payload_scope["title"], "refactor(beifong): migrate deprecated pydantic API calls (1 file)")
        
        # Test custom title override
        payload_custom = GitHubClient.generate_pr_markdown("owner/repo", audit_results, custom_title="[Beifong] Modernize Pydantic v2")
        self.assertEqual(payload_custom["title"], "[Beifong] Modernize Pydantic v2")

    @patch.object(GitHubPRHunter, "get_authenticated_user")
    @patch.object(GitHubPRHunter, "get_default_branch")
    @patch.object(GitHubPRHunter, "get_branch_sha")
    def test_audit_and_pr_repository_filters_target_path(self, mock_sha, mock_branch, mock_user):
        mock_user.return_value = "test-user"
        mock_branch.return_value = "main"
        mock_sha.return_value = "abc12345"
        
        hunter = GitHubPRHunter(github_token="fake_token")
        hunter.client.get_repo_file_tree = MagicMock(return_value=[
            {"path": "apps/beifong/models/podcast.py", "type": "blob"},
            {"path": "apps/beifong/models/user.py", "type": "blob"},
            {"path": "apps/other_app/server.py", "type": "blob"},
            {"path": "readme.md", "type": "blob"}
        ])
        hunter.client.fetch_file_content = MagicMock(return_value="import os\n")
        
        # Run with target_path="beifong" in dry_run mode
        res = hunter.audit_and_pr_repository(
            repo_name="owner/repo",
            dry_run=True,
            target_path="beifong"
        )
        self.assertEqual(res["status"], "clean")

    @patch.object(GitHubPRHunter, "get_authenticated_user")
    @patch.object(GitHubPRHunter, "get_default_branch")
    @patch.object(GitHubPRHunter, "get_branch_sha")
    def test_audit_and_pr_monorepo_auto_discovery(self, mock_sha, mock_branch, mock_user):
        mock_user.return_value = "test-user"
        mock_branch.return_value = "main"
        mock_sha.return_value = "abc12345"

        hunter = GitHubPRHunter(github_token="fake_token")
        hunter.client.get_repo_file_tree = MagicMock(return_value=[
            {"path": "rag_tutorials/requirements.txt", "type": "blob"},
            {"path": "rag_tutorials/advanced_rag.py", "type": "blob"},
            {"path": "agent_teams/requirements.txt", "type": "blob"},
            {"path": "agent_teams/agent.py", "type": "blob"},
        ])

        def fake_fetch(repo, path, ref="main"):
            if path == "rag_tutorials/advanced_rag.py":
                return "import openai\nopenai.ChatCompletion.create()\n"
            elif path == "rag_tutorials/requirements.txt":
                return "openai==0.28.0\n"
            return "import os\n"

        hunter.client.fetch_file_content = MagicMock(side_effect=fake_fetch)
        hunter.engine.audit_code = MagicMock(return_value={
            "has_breaking_changes": True,
            "refactored_code": "from openai import OpenAI\nclient = OpenAI()\nclient.chat.completions.create()\n",
            "detected_issues": [{"library": "openai", "deprecated_symbol": "ChatCompletion"}]
        })
        hunter.engine.generate_diff = MagicMock(return_value="--- a\n+++ b\n")

        # Run WITHOUT target_path in dry_run mode
        res = hunter.audit_and_pr_repository(
            repo_name="Shubhamsaboo/awesome-llm-apps",
            dry_run=True,
            target_path=None
        )

        self.assertEqual(res["status"], "preview")
        self.assertIn("rag_tutorials", res["title"])

    @patch.object(GitHubPRHunter, "get_authenticated_user")
    @patch.object(GitHubPRHunter, "get_default_branch")
    @patch.object(GitHubPRHunter, "get_branch_sha")
    def test_audit_and_pr_monorepo_multi_subproject_partitioning(self, mock_sha, mock_branch, mock_user):
        mock_user.return_value = "test-user"
        mock_branch.return_value = "main"
        mock_sha.return_value = "abc12345"

        hunter = GitHubPRHunter(github_token="fake_token")
        hunter.client.get_repo_file_tree = MagicMock(return_value=[
            {"path": "rag_tutorials/requirements.txt", "type": "blob"},
            {"path": "rag_tutorials/advanced_rag.py", "type": "blob"},
            {"path": "agent_teams/requirements.txt", "type": "blob"},
            {"path": "agent_teams/agent.py", "type": "blob"},
        ])

        def fake_fetch(repo, path, ref="main"):
            if path in ("rag_tutorials/advanced_rag.py", "agent_teams/agent.py"):
                return "import openai\nopenai.ChatCompletion.create()\n"
            elif path in ("rag_tutorials/requirements.txt", "agent_teams/requirements.txt"):
                return "openai==0.28.0\n"
            return "import os\n"

        hunter.client.fetch_file_content = MagicMock(side_effect=fake_fetch)
        hunter.engine.audit_code = MagicMock(return_value={
            "has_breaking_changes": True,
            "refactored_code": "from openai import OpenAI\nclient = OpenAI()\nclient.chat.completions.create()\n",
            "detected_issues": [{"library": "openai", "deprecated_symbol": "ChatCompletion"}]
        })
        hunter.engine.generate_diff = MagicMock(return_value="--- a\n+++ b\n")

        # Test with max_prs=2
        res2 = hunter.audit_and_pr_repository(
            repo_name="Shubhamsaboo/awesome-llm-apps",
            dry_run=True,
            per_subproject=True,
            max_prs=2
        )
        self.assertEqual(res2["status"], "preview")
        self.assertEqual(res2["total_subprojects_affected"], 2)
        self.assertEqual(len(res2["prs"]), 2)
        subprojects_in_prs = {pr["subproject"] for pr in res2["prs"]}
        self.assertIn("rag_tutorials", subprojects_in_prs)
        self.assertIn("agent_teams", subprojects_in_prs)

        # Test with max_prs=1 (Anti-Spam Guard enforces 1 PR preview/creation)
        res1 = hunter.audit_and_pr_repository(
            repo_name="Shubhamsaboo/awesome-llm-apps",
            dry_run=True,
            per_subproject=True,
            max_prs=1
        )
        self.assertEqual(res1["status"], "preview")
        self.assertEqual(res1["total_subprojects_affected"], 2)
        self.assertEqual(len(res1["prs"]), 1)

    @patch.object(GitHubPRHunter, "get_authenticated_user")
    @patch.object(GitHubPRHunter, "get_default_branch")
    @patch.object(GitHubPRHunter, "get_branch_sha")
    def test_audit_and_pr_monorepo_files_per_subproject_sampling(self, mock_sha, mock_branch, mock_user):
        mock_user.return_value = "test-user"
        mock_branch.return_value = "main"
        mock_sha.return_value = "abc12345"

        hunter = GitHubPRHunter(github_token="fake_token")
        # 3 subprojects, each having entrypoint app.py and helper.py
        hunter.client.get_repo_file_tree = MagicMock(return_value=[
            {"path": "sub1/requirements.txt", "type": "blob"},
            {"path": "sub1/helper.py", "type": "blob"},
            {"path": "sub1/app.py", "type": "blob"},
            {"path": "sub2/requirements.txt", "type": "blob"},
            {"path": "sub2/helper.py", "type": "blob"},
            {"path": "sub2/main.py", "type": "blob"},
            {"path": "sub3/requirements.txt", "type": "blob"},
            {"path": "sub3/helper.py", "type": "blob"},
            {"path": "sub3/agent.py", "type": "blob"},
        ])

        inspected_files = []
        def fake_fetch(repo, path, ref="main"):
            inspected_files.append(path)
            return "import os\n"

        hunter.client.fetch_file_content = MagicMock(side_effect=fake_fetch)
        hunter.engine.audit_code = MagicMock(return_value={"has_breaking_changes": False})

        hunter.audit_and_pr_repository(
            repo_name="Shubhamsaboo/awesome-llm-apps",
            dry_run=True,
            files_per_subproject=1
        )

        # Should prioritize entrypoints and pick exactly 1 file per subproject
        self.assertIn("sub1/app.py", inspected_files)
        self.assertIn("sub2/main.py", inspected_files)
        self.assertIn("sub3/agent.py", inspected_files)
        # Helpers should NOT be inspected when files_per_subproject=1
        self.assertNotIn("sub1/helper.py", inspected_files)
        self.assertNotIn("sub2/helper.py", inspected_files)


if __name__ == "__main__":
    unittest.main()


