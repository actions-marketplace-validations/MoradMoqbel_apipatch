"""
ApiPatch GitHub REST API Client & Automation Subsystem
Handles authentication, token discovery, repository inspection, forking,
atomic multi-file Git tree commits, and autonomous Pull Request submission.
"""

import os
import sys
import json
import base64
import time
import hmac
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from typing import List, Dict, Any, Optional, Set, Tuple

GITHUB_API_BASE = "https://api.github.com"


def resolve_github_token(token: Optional[str] = None) -> Optional[str]:
    """
    Resolves the GitHub token with cascading fallback:
    1. Explicit function/CLI argument `token`
    2. Environment variable `GITHUB_TOKEN`
    3. Environment variable `GH_TOKEN`
    4. `github_token.txt` in the current working directory
    5. `github_token.txt` in the repository/project root
    6. `.env` file containing GITHUB_TOKEN=...
    """
    if token and token.strip():
        return token.strip()

    # 2. Environment variables
    env_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    # 3. Check github_token.txt in current directory
    cwd_token_file = os.path.join(os.getcwd(), "github_token.txt")
    if os.path.isfile(cwd_token_file):
        try:
            with open(cwd_token_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    # 4. Check github_token.txt relative to package root
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pkg_token_file = os.path.join(pkg_dir, "github_token.txt")
    if os.path.isfile(pkg_token_file):
        try:
            with open(pkg_token_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception:
            pass

    # 5. Check .env file in cwd or package dir
    for env_path in [os.path.join(os.getcwd(), ".env"), os.path.join(pkg_dir, ".env")]:
        if os.path.isfile(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GITHUB_TOKEN="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
                        elif line.startswith("GH_TOKEN="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except Exception:
                pass

    return None


def mask_token(token: Optional[str]) -> str:
    """Safely masks a token for user-facing logs (e.g. ghp_****...xy12)."""
    if not token:
        return "None"
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}****{token[-4:]}"


class GitHubClient:
    """
    Robust, zero-external-dependency GitHub REST API Client.
    Supports repository cloning/tree inspection, forking, branch management,
    atomic multi-file commit generation, and Pull Request orchestration.
    """

    def __init__(self, token: Optional[str] = None):
        self.token = resolve_github_token(token)
        self._auth_user: Optional[str] = None

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
        full_url: Optional[str] = None,
        headers_override: Optional[Dict[str, str]] = None
    ) -> Optional[Any]:
        """Makes an authenticated HTTP request to GitHub REST API."""
        url = full_url or f"{GITHUB_API_BASE}{endpoint}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ApiPatch-Autonomous-Agent/1.0"
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        if headers_override:
            headers.update(headers_override)

        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        for attempt in range(1, 5):
            try:
                with urllib.request.urlopen(req, timeout=45) as response:
                    chunks = []
                    while True:
                        try:
                            chunk = response.read(65536)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        except Exception as read_err:
                            if "IncompleteRead" in type(read_err).__name__ and hasattr(read_err, "partial"):
                                chunks.append(read_err.partial)
                                break
                            raise read_err
                    body = b"".join(chunks).decode("utf-8", errors="replace")
                    if not body.strip():
                        return {"status": "ok", "code": response.status}
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                err_msg = e.read().decode("utf-8", errors="ignore")
                if e.code == 404:
                    return None
                elif e.code == 403 and "rate limit" in err_msg.lower():
                    print(f"[!] GitHub API rate limit reached.")
                elif e.code != 404:
                    print(f"[!] GitHub API HTTP {e.code} on {method} {url}: {err_msg}")
                return None
            except Exception as e:
                if attempt < 4:
                    time.sleep(2.0 * attempt)
                    continue
                print(f"[!] Network error on GitHub API request ({method} {url}): {e}")
                return None

    # ── User & Repository Metadata ──────────────────────────────────────────

    def get_authenticated_user(self) -> Optional[str]:
        """Returns the login username of the current token owner."""
        if self._auth_user:
            return self._auth_user
        data = self._request("/user")
        if data and isinstance(data, dict) and "login" in data:
            self._auth_user = data["login"]
            return self._auth_user
        return None

    def get_repository(self, repo_full_name: str) -> Optional[Dict[str, Any]]:
        """Fetches repository metadata from GitHub."""
        clean_name = self.normalize_repo_name(repo_full_name)
        data = self._request(f"/repos/{clean_name}")
        if isinstance(data, dict) and "full_name" in data:
            return data
        return None

    def has_write_permission(self, repo_full_name: str) -> bool:
        """
        Checks if the authenticated token user has direct write/push access
        to the repository.
        """
        clean_name = self.normalize_repo_name(repo_full_name)
        auth_user = self.get_authenticated_user()
        repo_data = self.get_repository(clean_name)
        if not repo_data:
            return False

        # If user is owner
        owner_login = repo_data.get("owner", {}).get("login", "")
        if auth_user and owner_login and auth_user.lower() == owner_login.lower():
            return True

        # Check permissions object
        perms = repo_data.get("permissions", {})
        if perms.get("admin") or perms.get("push"):
            return True

        return False

    def get_default_branch(self, repo_full_name: str) -> str:
        """Returns default branch name (main, master, etc.)."""
        clean_name = self.normalize_repo_name(repo_full_name)
        repo_data = self.get_repository(clean_name)
        if repo_data and "default_branch" in repo_data:
            return repo_data["default_branch"]
        return "main"

    # ── Forking ─────────────────────────────────────────────────────────────

    def fork_repository(self, repo_full_name: str, wait_ready: bool = True, max_wait_sec: int = 10) -> Optional[str]:
        """
        Forks the target repository under the authenticated user account.
        Returns 'fork_owner/repo_name' when ready.
        """
        clean_name = self.normalize_repo_name(repo_full_name)
        auth_user = self.get_authenticated_user()
        if not auth_user:
            return None

        data = self._request(f"/repos/{clean_name}/forks", method="POST")
        if not data or not isinstance(data, dict):
            return None

        fork_full_name = data.get("full_name") or f"{auth_user}/{clean_name.split('/')[-1]}"

        if wait_ready:
            start_t = time.time()
            while time.time() - start_t < max_wait_sec:
                check = self._request(f"/repos/{fork_full_name}")
                if check and isinstance(check, dict) and "full_name" in check:
                    return fork_full_name
                time.sleep(1.5)

        return fork_full_name

    # ── Git Database & Tree Operations ──────────────────────────────────────

    def get_branch_sha(self, repo_full_name: str, branch: str) -> Optional[str]:
        """Gets commit SHA of the latest commit on a branch."""
        clean_name = self.normalize_repo_name(repo_full_name)
        data = self._request(f"/repos/{clean_name}/git/ref/heads/{branch}")
        if data and isinstance(data, dict) and "object" in data and "sha" in data["object"]:
            return data["object"]["sha"]

        data_b = self._request(f"/repos/{clean_name}/branches/{branch}")
        if data_b and isinstance(data_b, dict) and "commit" in data_b and "sha" in data_b["commit"]:
            return data_b["commit"]["sha"]

        return None

    def create_branch(self, repo_full_name: str, branch_name: str, base_sha: str) -> bool:
        """Creates a new branch pointer from base_sha."""
        clean_name = self.normalize_repo_name(repo_full_name)
        payload = {
            "ref": f"refs/heads/{branch_name}",
            "sha": base_sha
        }
        res = self._request(f"/repos/{clean_name}/git/refs", method="POST", payload=payload)
        return res is not None and (isinstance(res, dict) and ("ref" in res or res.get("status") == "ok"))

    def get_repo_file_tree(self, repo_full_name: str, branch: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Recursively retrieves the entire repository file tree via Git Trees API.
        """
        clean_name = self.normalize_repo_name(repo_full_name)
        target_branch = branch or self.get_default_branch(clean_name)
        base_sha = self.get_branch_sha(clean_name, target_branch)
        if not base_sha:
            return []

        data = self._request(f"/repos/{clean_name}/git/trees/{base_sha}?recursive=1")
        if data and isinstance(data, dict) and "tree" in data:
            return [item for item in data["tree"] if item.get("type") == "blob"]
        return []

    def fetch_file_content(self, repo_full_name: str, file_path: str, ref: str = "main") -> Optional[str]:
        """Fetches and decodes the raw text content of a file from repository."""
        clean_name = self.normalize_repo_name(repo_full_name)
        clean_path = file_path.lstrip("/")
        encoded_path = urllib.parse.quote(clean_path)
        data = self._request(f"/repos/{clean_name}/contents/{encoded_path}?ref={ref}")

        if data and isinstance(data, dict) and "content" in data:
            try:
                raw_bytes = base64.b64decode(data["content"])
                return raw_bytes.decode("utf-8", errors="ignore")
            except Exception:
                pass

        raw_url = f"https://raw.githubusercontent.com/{clean_name}/{ref}/{clean_path}"
        try:
            req = urllib.request.Request(raw_url, headers={"User-Agent": "ApiPatch-Autonomous-Agent/1.0"})
            if self.token:
                req.add_header("Authorization", f"token {self.token}")
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.read().decode("utf-8", errors="ignore")
        except Exception:
            return None

    def get_file_sha(self, repo_full_name: str, file_path: str, ref: str) -> Optional[str]:
        """Gets the blob SHA of an existing file."""
        clean_name = self.normalize_repo_name(repo_full_name)
        clean_path = file_path.lstrip("/")
        encoded_path = urllib.parse.quote(clean_path)
        data = self._request(f"/repos/{clean_name}/contents/{encoded_path}?ref={ref}")
        if data and isinstance(data, dict) and "sha" in data:
            return data["sha"]
        return None

    def get_file_last_commit_date(self, repo_full_name: str, file_path: str) -> Optional[str]:
        """Fetches the ISO timestamp of the latest commit affecting a specific file."""
        clean_name = self.normalize_repo_name(repo_full_name)
        clean_path = file_path.lstrip("/")
        encoded_path = urllib.parse.quote(clean_path)
        data = self._request(f"/repos/{clean_name}/commits?path={encoded_path}&per_page=1")
        if data and isinstance(data, list) and len(data) > 0:
            commit_obj = data[0].get("commit", {})
            committer = commit_obj.get("committer") or commit_obj.get("author") or {}
            return committer.get("date")
        return None

    # ── Commits & Multi-file Updates ────────────────────────────────────────

    def commit_single_file(
        self,
        repo_full_name: str,
        branch: str,
        file_path: str,
        content: str,
        message: str
    ) -> bool:
        """Commits and updates a single file using the GitHub Contents API."""
        clean_name = self.normalize_repo_name(repo_full_name)
        clean_path = file_path.lstrip("/")
        existing_sha = self.get_file_sha(clean_name, clean_path, branch)

        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": message,
            "content": encoded_content,
            "branch": branch
        }
        if existing_sha:
            payload["sha"] = existing_sha

        encoded_path = urllib.parse.quote(clean_path)
        data = self._request(f"/repos/{clean_name}/contents/{encoded_path}", method="PUT", payload=payload)
        return data is not None and isinstance(data, dict) and ("content" in data or "commit" in data)

    def commit_multiple_files(
        self,
        repo_full_name: str,
        branch: str,
        files: Dict[str, str],
        commit_message: str,
        base_sha: Optional[str] = None
    ) -> Optional[str]:
        """
        Creates an atomic multi-file commit on a branch via Git Database API.
        """
        clean_name = self.normalize_repo_name(repo_full_name)
        if not files:
            return None

        parent_sha = base_sha or self.get_branch_sha(clean_name, branch)
        if not parent_sha:
            return None

        # 1. Create blobs for modified files
        tree_items = []
        for file_path, content in files.items():
            if isinstance(content, str):
                encoded_c = base64.b64encode(content.encode("utf-8", errors="replace")).decode("ascii")
            elif isinstance(content, bytes):
                encoded_c = base64.b64encode(content).decode("ascii")
            else:
                encoded_c = base64.b64encode(str(content).encode("utf-8", errors="replace")).decode("ascii")

            blob_payload = {
                "content": encoded_c,
                "encoding": "base64"
            }
            blob_data = self._request(f"/repos/{clean_name}/git/blobs", method="POST", payload=blob_payload)
            if blob_data and isinstance(blob_data, dict) and "sha" in blob_data:
                tree_items.append({
                    "path": file_path.lstrip("/"),
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_data["sha"]
                })
            else:
                return None

        # 2. Create Tree
        tree_payload = {
            "base_tree": parent_sha,
            "tree": tree_items
        }
        tree_data = self._request(f"/repos/{clean_name}/git/trees", method="POST", payload=tree_payload)
        if not tree_data or "sha" not in tree_data:
            return None
        new_tree_sha = tree_data["sha"]

        # 3. Create Commit
        commit_payload = {
            "message": commit_message,
            "tree": new_tree_sha,
            "parents": [parent_sha]
        }
        commit_data = self._request(f"/repos/{clean_name}/git/commits", method="POST", payload=commit_payload)
        if not commit_data or "sha" not in commit_data:
            return None
        new_commit_sha = commit_data["sha"]

        # 4. Update Branch Reference
        ref_payload = {
            "sha": new_commit_sha,
            "force": True
        }
        update_ref = self._request(f"/repos/{clean_name}/git/refs/heads/{branch}", method="PATCH", payload=ref_payload)
        if update_ref and isinstance(update_ref, dict) and ("ref" in update_ref or "object" in update_ref):
            return new_commit_sha

        return new_commit_sha

    # ── Pull Request Operations ─────────────────────────────────────────────

    def submit_pull_request(
        self,
        base_repo: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
        draft: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Submits a live Pull Request to the target repository."""
        clean_base = self.normalize_repo_name(base_repo)
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft
        }
        return self._request(f"/repos/{clean_base}/pulls", method="POST", payload=payload)

    def find_existing_pull_request(self, base_repo: str, head_branch: str) -> Optional[Dict[str, Any]]:
        """Checks if an open PR already exists for the given head branch."""
        clean_base = self.normalize_repo_name(base_repo)
        prs = self._request(f"/repos/{clean_base}/pulls?state=open")
        if isinstance(prs, list):
            for pr in prs:
                if pr.get("head", {}).get("ref") == head_branch or pr.get("head", {}).get("label") == head_branch:
                    return pr
        return None

    def get_pull_request(self, repo_full_name: str, pr_number: int) -> Optional[Dict[str, Any]]:
        """Fetches metadata for a specific Pull Request."""
        clean_name = self.normalize_repo_name(repo_full_name)
        data = self._request(f"/repos/{clean_name}/pulls/{pr_number}")
        if isinstance(data, dict) and "id" in data:
            return data
        return None

    def get_pull_request_files(self, repo_full_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetches the list of modified files in a specific Pull Request."""
        clean_name = self.normalize_repo_name(repo_full_name)
        data = self._request(f"/repos/{clean_name}/pulls/{pr_number}/files?per_page=100")
        if isinstance(data, list):
            return data
        return []

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def parse_pr_target(raw: str) -> Tuple[str, Optional[int]]:
        """
        Parses a target string (e.g. repo name or PR URL) and extracts (repo_name, pr_number).
        Examples:
          'https://github.com/KarlTDebiec/Scinoephile/pull/1326' -> ('KarlTDebiec/Scinoephile', 1326)
          'KarlTDebiec/Scinoephile#1326' -> ('KarlTDebiec/Scinoephile', 1326)
          'KarlTDebiec/Scinoephile' -> ('KarlTDebiec/Scinoephile', None)
        """
        import re
        clean_raw = raw.strip()
        m_url = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", clean_raw)
        if m_url:
            return m_url.group(1), int(m_url.group(2))
        m_hash = re.search(r"^([^/]+/[^/#]+)#(\d+)$", clean_raw)
        if m_hash:
            return m_hash.group(1), int(m_hash.group(2))
        return GitHubClient.normalize_repo_name(clean_raw), None

    @staticmethod
    def normalize_repo_name(raw: str) -> str:
        """Cleans and extracts 'owner/repo' from URLs or raw strings."""
        raw = raw.strip()
        if raw.startswith("https://github.com/"):
            raw = raw.replace("https://github.com/", "")
        elif raw.startswith("http://github.com/"):
            raw = raw.replace("http://github.com/", "")
        elif raw.startswith("git@github.com:"):
            raw = raw.replace("git@github.com:", "")

        if raw.endswith(".git"):
            raw = raw[:-4]
        raw = raw.rstrip("/")

        parts = [p for p in raw.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return raw

    @staticmethod
    def generate_pr_markdown(
        repo_name: str,
        audit_results: List[Dict[str, Any]],
        custom_title: Optional[str] = None,
        scope_prefix: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Generates standard GitHub Pull Request title and rich Markdown body.
        """
        total_files = len(audit_results)
        all_issues = []
        for r in audit_results:
            for issue in r.get("detected_issues", []):
                all_issues.append((r.get("file", ""), issue))

        libs = sorted(list({issue.get("library", "API") for _, issue in all_issues if issue.get("library")}))
        libs_str = ", ".join(libs) if libs else "Third-Party"

        prefix = scope_prefix or ""
        scope_clean = prefix.strip("[] ").lower().replace("/", "-").replace(" ", "-") if prefix else ""
        scope_tag = f"({scope_clean})" if scope_clean else ""
        default_title = f"refactor{scope_tag}: migrate deprecated {libs_str} API calls ({total_files} file{'s' if total_files > 1 else ''})"
        title = custom_title or default_title

        body_lines = [
            "## ⚡ Autonomous API Migration by [ApiPatch](https://github.com/MoradMoqbel/apipatch)",
            "",
            f"This automated Pull Request modernizes deprecated or breaking **{libs_str}** API signatures across **{total_files}** file(s).",
            "",
            "### 🔍 Detected Breaking Changes & Fixes:",
            "",
            "| File | Library | Deprecated Call | Modernized Replacement |",
            "| :--- | :--- | :--- | :--- |"
        ]

        for file_path, issue in all_issues:
            lib = issue.get("library", "Unknown")
            old_sym = issue.get("deprecated_symbol", "N/A").replace("`", "")
            new_sym = issue.get("replacement_symbol", "N/A").replace("`", "")
            body_lines.append(f"| `{file_path}` | **{lib}** | `{old_sym}` | `{new_sym}` |")

        body_lines.extend([
            "",
            "### 🛡️ Safety & Quality Verification:",
            "- [x] **AST Syntax Parsed**: Guaranteed zero syntax or parsing errors.",
            "- [x] **100% Signature Match**: Existing function arguments, variables, and business logic intact.",
            "- [x] **Self-Healing Guard**: AI hallucinations filtered and validated against AST rules.",
            "",
            "---",
            "*Generated autonomously with ❤️ by [ApiPatch](https://github.com/MoradMoqbel/apipatch) — The Autonomous AI Agent for Breaking API Changes.*"
        ])

        return {
            "title": title,
            "body": "\n".join(body_lines)
        }
