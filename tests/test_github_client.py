"""
Unit tests for GitHubClient and token discovery
"""

import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock
from apipatch.github_client import (
    GitHubClient,
    resolve_github_token,
    mask_token
)


class TestGitHubClient(unittest.TestCase):

    def test_mask_token(self):
        self.assertEqual(mask_token(None), "None")
        self.assertEqual(mask_token("1234"), "****")
        self.assertEqual(mask_token("ghp_1234567890abcdef"), "ghp_****cdef")

    def test_normalize_repo_name(self):
        client = GitHubClient(token="fake_token")
        self.assertEqual(client.normalize_repo_name("owner/repo"), "owner/repo")
        self.assertEqual(client.normalize_repo_name("https://github.com/owner/repo.git"), "owner/repo")
        self.assertEqual(client.normalize_repo_name("https://github.com/owner/repo/"), "owner/repo")
        self.assertEqual(client.normalize_repo_name("git@github.com:owner/repo.git"), "owner/repo")

    def test_token_resolution_explicit_arg(self):
        token = resolve_github_token("explicit_token_123")
        self.assertEqual(token, "explicit_token_123")

    @patch.dict(os.environ, {"GITHUB_TOKEN": "env_token_456"}, clear=False)
    def test_token_resolution_env(self):
        token = resolve_github_token(None)
        self.assertEqual(token, "env_token_456")

    def test_token_resolution_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                token_file = os.path.join(tmpdir, "github_token.txt")
                with open(token_file, "w", encoding="utf-8") as f:
                    f.write("file_token_789\n")

                with patch.dict(os.environ, {}, clear=True):
                    token = resolve_github_token(None)
                    self.assertEqual(token, "file_token_789")
            finally:
                os.chdir(old_cwd)

    @patch.object(GitHubClient, "_request")
    def test_has_write_permission_as_owner(self, mock_req):
        mock_req.side_effect = [
            {"login": "morad"},  # /user
            {"full_name": "morad/repo", "owner": {"login": "morad"}}  # /repos/morad/repo
        ]
        client = GitHubClient(token="valid_token")
        self.assertTrue(client.has_write_permission("morad/repo"))

    @patch.object(GitHubClient, "_request")
    def test_has_write_permission_via_push_flag(self, mock_req):
        mock_req.side_effect = [
            {"login": "contributor"},  # /user
            {"full_name": "org/repo", "owner": {"login": "org"}, "permissions": {"push": True}}
        ]
        client = GitHubClient(token="valid_token")
        self.assertTrue(client.has_write_permission("org/repo"))

    @patch.object(GitHubClient, "_request")
    def test_get_repo_file_tree(self, mock_req):
        mock_req.side_effect = [
            {"default_branch": "main"},
            {"object": {"sha": "sha123"}},
            {
                "tree": [
                    {"path": "main.py", "type": "blob", "size": 100},
                    {"path": "docs", "type": "tree"},
                    {"path": "utils.py", "type": "blob", "size": 200}
                ]
            }
        ]
        client = GitHubClient(token="valid_token")
        tree = client.get_repo_file_tree("owner/repo")
        self.assertEqual(len(tree), 2)
        self.assertEqual(tree[0]["path"], "main.py")
        self.assertEqual(tree[1]["path"], "utils.py")

    @patch.object(GitHubClient, "_request")
    def test_commit_multiple_files(self, mock_req):
        # 1. blob1, 2. blob2, 3. tree, 4. commit, 5. patch ref
        mock_req.side_effect = [
            {"sha": "blob_sha_1"},
            {"sha": "blob_sha_2"},
            {"sha": "tree_sha_1"},
            {"sha": "commit_sha_new"},
            {"ref": "refs/heads/apipatch/migrate", "object": {"sha": "commit_sha_new"}}
        ]
        client = GitHubClient(token="valid_token")
        files = {
            "services/llm.py": "import openai\nclient = openai.OpenAI()\n",
            "config.py": "MODEL = 'gpt-4o'\n"
        }
        res_sha = client.commit_multiple_files(
            repo_full_name="owner/repo",
            branch="apipatch/migrate",
            files=files,
            commit_message="[ApiPatch] Modernize API calls",
            base_sha="parent_sha_123"
        )
        self.assertEqual(res_sha, "commit_sha_new")

    def test_generate_pr_markdown(self):
        audit_results = [{
            "file": "services/payments.py",
            "detected_issues": [{
                "library": "stripe",
                "deprecated_symbol": "stripe.Charge.create()",
                "replacement_symbol": "stripe.PaymentIntent.create()",
                "description": "Migrate Charge to PaymentIntent"
            }]
        }]
        md = GitHubClient.generate_pr_markdown("owner/repo", audit_results)
        self.assertIn("migrate deprecated stripe api calls", md["title"].lower())
        self.assertIn("services/payments.py", md["body"])
        self.assertIn("stripe.PaymentIntent.create()", md["body"])

    def test_parse_pr_target(self):
        repo, pr = GitHubClient.parse_pr_target("https://github.com/KarlTDebiec/Scinoephile/pull/1326")
        self.assertEqual(repo, "KarlTDebiec/Scinoephile")
        self.assertEqual(pr, 1326)

        repo2, pr2 = GitHubClient.parse_pr_target("KarlTDebiec/Scinoephile#42")
        self.assertEqual(repo2, "KarlTDebiec/Scinoephile")
        self.assertEqual(pr2, 42)

        repo3, pr3 = GitHubClient.parse_pr_target("romanvm/python-web-pdb")
        self.assertEqual(repo3, "romanvm/python-web-pdb")
        self.assertIsNone(pr3)


if __name__ == "__main__":
    unittest.main()
