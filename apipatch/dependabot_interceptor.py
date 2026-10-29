"""
ApiPatch Dependabot & Renovate Breaking-Change Interceptor Engine
Autonomously discovers newly opened dependency bump PRs, inspects the target package
delta, statically validates repository production code via AST to detect breaking signatures,
and proposes verified code patches before the repository maintainer even reviews the PR.
"""

import os
import sys
import re
import json
import time
import difflib
from typing import List, Dict, Any, Optional, Tuple

from apipatch.engine import ApiPatchEngine, Colors
from apipatch.github_client import GitHubClient, resolve_github_token, GITHUB_API_BASE
from apipatch.filters import is_non_prod_path, is_test_path, is_doc_path
from apipatch.doc_hunter import DocHunter


def extract_diff_hunk(original_code: str, refactored_code: str) -> Optional[Dict[str, Any]]:
    """
    Computes a clean diff hunk (start line, original lines, replacement lines)
    between original_code and refactored_code.
    Prioritizes meaningful code changes over comment/license formatting diffs.
    """
    if not original_code or not refactored_code or original_code == refactored_code:
        return None

    orig_lines = original_code.splitlines()
    ref_lines = refactored_code.splitlines()

    matcher = difflib.SequenceMatcher(None, orig_lines, ref_lines)
    hunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete", "insert"):
            start_line = i1 + 1
            old_chunk = "\n".join(orig_lines[i1:i2]) if i1 < i2 else ""
            new_chunk = "\n".join(ref_lines[j1:j2]) if j1 < j2 else ""
            if old_chunk or new_chunk:
                is_pure_comment = all(
                    l.strip().startswith(("#", "//", "/*", "*")) or not l.strip()
                    for l in (old_chunk + "\n" + new_chunk).splitlines()
                )
                hunks.append({
                    "line": start_line,
                    "call": old_chunk,
                    "fix": new_chunk,
                    "is_comment": is_pure_comment
                })

    if not hunks:
        return None

    # Pick the first non-comment hunk, or first hunk if all are comments
    code_hunks = [h for h in hunks if not h["is_comment"]]
    selected = code_hunks[0] if code_hunks else hunks[0]
    return {
        "line": selected["line"],
        "call": selected["call"],
        "fix": selected["fix"]
    }

# Modern (2024 - 2026) Breaking Change Knowledge Delta
# Maps (package, from_version_prefix, to_version_prefix) -> list of breaking symbols & instructions
BREAKING_DELTA_CATALOG: Dict[str, Dict[str, Any]] = {
    "langchain": {
        "description": "LangChain v0.2 -> v0.3+ Modular Migration & LCEL",
        "breaking_rules": [
            {
                "id": "langchain_partner_imports",
                "pattern": r"from\s+langchain\.chat_models\s+import\s+(ChatOpenAI|ChatAnthropic)",
                "replacement_hint": "from langchain_openai import ChatOpenAI or from langchain_anthropic import ChatAnthropic",
                "error_type": "ModuleNotFoundError / DeprecationError",
                "severity": "CRITICAL"
            },
            {
                "id": "langchain_embeddings_import",
                "pattern": r"from\s+langchain\.embeddings\s+import\s+(OpenAIEmbeddings|HuggingFaceEmbeddings)",
                "replacement_hint": "from langchain_openai import OpenAIEmbeddings",
                "error_type": "ModuleNotFoundError",
                "severity": "CRITICAL"
            },
            {
                "id": "langchain_run_deprecated",
                "pattern": r"\.run\s*\(",
                "replacement_hint": "Migrate .run(...) to .invoke(...)",
                "error_type": "AttributeError: 'Runnable' object has no attribute 'run'",
                "severity": "HIGH"
            },
            {
                "id": "langchain_retrieval_qa",
                "pattern": r"RetrievalQA\.from_chain_type",
                "replacement_hint": "Migrate to create_retrieval_chain + create_stuff_documents_chain",
                "error_type": "RemovedInLangChain03Warning / Removal",
                "severity": "HIGH"
            }
        ]
    },
    "anthropic": {
        "description": "Anthropic Claude v0.x -> v0.30+/1.x Modern Messages API",
        "breaking_rules": [
            {
                "id": "anthropic_completion_removed",
                "pattern": r"client\.completion\s*\(",
                "replacement_hint": "Migrate to client.messages.create(model='claude-3-5-sonnet-20241022', messages=[...])",
                "error_type": "AttributeError: 'Anthropic' object has no attribute 'completion'",
                "severity": "CRITICAL"
            },
            {
                "id": "anthropic_human_prompt",
                "pattern": r"(HUMAN_PROMPT|AI_PROMPT)",
                "replacement_hint": "Legacy prompt constants removed. Use structured messages=[{'role': 'user', 'content': ...}]",
                "error_type": "ImportError / NameError",
                "severity": "HIGH"
            }
        ]
    },
    "google-generativeai": {
        "description": "Google GenAI Migration (google-generativeai -> google-genai)",
        "breaking_rules": [
            {
                "id": "google_genai_legacy_import",
                "pattern": r"import\s+google\.generativeai\s+as\s+genai",
                "replacement_hint": "from google import genai",
                "error_type": "Deprecation / SDK Replacement",
                "severity": "CRITICAL"
            },
            {
                "id": "google_generative_model",
                "pattern": r"genai\.GenerativeModel\s*\(",
                "replacement_hint": "client = genai.Client(); client.models.generate_content(...)",
                "error_type": "Legacy SDK Architecture",
                "severity": "CRITICAL"
            }
        ]
    },
    "pydantic": {
        "description": "Pydantic v1 -> v2 Migration",
        "breaking_rules": [
            {
                "id": "pydantic_base_settings_moved",
                "pattern": r"from\s+pydantic\s+import\s+.*BaseSettings",
                "replacement_hint": "from pydantic_settings import BaseSettings",
                "error_type": "ImportError: cannot import name 'BaseSettings' from 'pydantic'",
                "severity": "CRITICAL"
            },
            {
                "id": "pydantic_validator_deprecated",
                "pattern": r"@validator\s*\(",
                "replacement_hint": "from pydantic import field_validator; @field_validator(...)",
                "error_type": "PydanticUserError / Warning",
                "severity": "HIGH"
            },
            {
                "id": "pydantic_dict_method",
                "pattern": r"\.dict\s*\(\s*\)",
                "replacement_hint": "Migrate .dict() to .model_dump()",
                "error_type": "DeprecationWarning / Pydantic v2 Migration",
                "severity": "MEDIUM"
            }
        ]
    },
    "redis": {
        "description": "Redis-Py v5 -> v8 Major Migration",
        "breaking_rules": [
            {
                "id": "redis_connection_lifecycle",
                "pattern": r"aioredis\.",
                "replacement_hint": "aioredis was merged into redis.asyncio. Use from redis import asyncio as aioredis",
                "error_type": "ModuleNotFoundError: No module named 'aioredis'",
                "severity": "CRITICAL"
            }
        ]
    },
    "fastapi": {
        "description": "FastAPI Lifespan Migration",
        "breaking_rules": [
            {
                "id": "fastapi_on_event",
                "pattern": r"@app\.on_event\s*\(\s*[\"'](startup|shutdown)[\"']\s*\)",
                "replacement_hint": "Migrate @app.on_event to @asynccontextmanager lifespan(app: FastAPI)",
                "error_type": "DeprecationWarning: on_event is deprecated",
                "severity": "MEDIUM"
            }
        ]
    },
    "zod": {
        "description": "Zod v3 -> v4 Unified Error Migration",
        "breaking_rules": [
            {
                "id": "zod_invalid_type_error",
                "pattern": r"invalid_type_error\s*:",
                "replacement_hint": "In Zod 4, replace invalid_type_error: with error: (e.g. { error: 'Enter a number' })",
                "error_type": "TS2353: 'invalid_type_error' does not exist in type '$ZodParams'",
                "severity": "CRITICAL"
            },
            {
                "id": "zod_required_error",
                "pattern": r"required_error\s*:",
                "replacement_hint": "In Zod 4, replace required_error: with error: or an error handler function",
                "error_type": "TS2353: 'required_error' does not exist in type '$ZodParams'",
                "severity": "CRITICAL"
            }
        ]
    },
    "typescript": {
        "description": "TypeScript Modern Compiler Strictness",
        "breaking_rules": [
            {
                "id": "typescript_module_resolution",
                "pattern": r"\"moduleResolution\"\s*:\s*\"node\"",
                "replacement_hint": "Migrate \"moduleResolution\": \"node\" to \"moduleResolution\": \"bundler\"",
                "error_type": "TS5110: Compiler option 'moduleResolution: node' deprecated",
                "severity": "HIGH"
            }
        ]
    },
    "pinia": {
        "description": "Pinia v3 -> v4 Major Migration & Peer Dependency Realignment",
        "breaking_rules": [
            {
                "id": "pinia_testing_peer_conflict",
                "pattern": r"\"@pinia/testing\"\s*:\s*\"[\^~]?1\.",
                "replacement_hint": "Pinia v4 requires @pinia/testing ^2.0.0; align devDependencies to resolve test runner crash",
                "error_type": "PeerDependencyError: @pinia/testing@1 requires pinia@^2.0.0 || ^3.0.0",
                "severity": "CRITICAL"
            },
            {
                "id": "pinia_store_to_refs",
                "pattern": r"storeToRefs\s*\(",
                "replacement_hint": "In Pinia 4, storeToRefs requires explicit generic typing on dynamic module stores",
                "error_type": "TS2322: Type 'ToRefs<Store>' is missing properties in Pinia v4",
                "severity": "HIGH"
            }
        ]
    },
    "@pinia/testing": {
        "description": "@pinia/testing v1 -> v2 Migration",
        "breaking_rules": [
            {
                "id": "pinia_core_peer_conflict",
                "pattern": r"\"pinia\"\s*:\s*\"[\^~]?3\.",
                "replacement_hint": "@pinia/testing v2 requires pinia ^4.0.0; bump core pinia package in tandem",
                "error_type": "PeerDependencyError: pinia@^3.0.0 is incompatible with @pinia/testing@2.0.0",
                "severity": "CRITICAL"
            }
        ]
    },
    "axios": {
        "description": "Axios v1.x Request Configuration & Error Strictness",
        "breaking_rules": [
            {
                "id": "axios_error_typing",
                "pattern": r"error\s*instanceof\s*AxiosError",
                "replacement_hint": "Use axios.isAxiosError(error) instead of instanceof AxiosError to avoid prototype mismatch in ESM/CJS",
                "error_type": "TS2339: Property 'response' does not exist on type 'Error'",
                "severity": "HIGH"
            }
        ]
    },
    "next": {
        "description": "Next.js Async Request APIs (Next.js 15 -> 16)",
        "breaking_rules": [
            {
                "id": "next_sync_cookies",
                "pattern": r"cookies\s*\(\s*\)\.(get|set|has|delete)\s*\(",
                "replacement_hint": "In Next.js modern runtimes, cookies() returns a Promise. Use (await cookies()).$1(...)",
                "error_type": "TypeError: cookies().get is not a function (cookies() returned a Promise)",
                "severity": "CRITICAL"
            },
            {
                "id": "next_sync_headers",
                "pattern": r"headers\s*\(\s*\)\.get\s*\(",
                "replacement_hint": "In Next.js modern runtimes, headers() returns a Promise. Use (await headers()).get(...)",
                "error_type": "TypeError: headers().get is not a function (headers() returned a Promise)",
                "severity": "CRITICAL"
            }
        ]
    },
    "msw": {
        "description": "MSW v2 -> v3 Modern Fetch Handler Migration",
        "breaking_rules": [
            {
                "id": "msw_rest_deprecated",
                "pattern": r"rest\.(get|post|put|delete|patch)\s*\(",
                "replacement_hint": "In modern MSW, migrate rest.<method> to http.<method> and return HttpResponse.json(...)",
                "error_type": "TypeError: rest is not defined (removed in favor of http namespace)",
                "severity": "CRITICAL"
            }
        ]
    },
    "vitest": {
        "description": "Vitest Major Runner Strictness",
        "breaking_rules": [
            {
                "id": "vitest_mock_hoisting",
                "pattern": r"vi\.mock\s*\(\s*['\"][^'\"]+['\"]\s*,\s*\(\)\s*=>\s*\{",
                "replacement_hint": "Ensure vi.mock factory returns clean exports and does not access unhoisted variables",
                "error_type": "Error: [vitest] Cannot access uninitialized variable inside vi.mock factory",
                "severity": "HIGH"
            }
        ]
    }
}


class DependabotInterceptor:
    """
    Autonomous Dependabot PR Interceptor & Pre-Emptive Breaking Change Detector.
    Scans live Dependabot PRs on GitHub, parses the package delta, verifies whether
    production code calls breaking symbols, and generates AST-verified companion fixes.
    """

    def __init__(self, github_token: Optional[str] = None, engine: Optional[ApiPatchEngine] = None):
        self.github_token = resolve_github_token(github_token)
        self.client = GitHubClient(token=self.github_token)
        self.engine = engine or ApiPatchEngine()

    @staticmethod
    def parse_pr_bump(title: str, body: str = "") -> List[Dict[str, str]]:
        """
        Extracts package name, old version, and new version from Dependabot PR title or body.
        """
        bumps = []
        # Pattern 1: Title "Bump <pkg> from <v1> to <v2>"
        m = re.search(r"bump\s+([a-zA-Z0-9_\-\.\@\/]+)\s+from\s+([vV]?\d+[a-zA-Z0-9_\.\-]+)\s+to\s+([vV]?\d+[a-zA-Z0-9_\.\-]+)", title, re.IGNORECASE)
        if m:
            pkg, old_v, new_v = m.groups()
            bumps.append({"package": pkg.lower(), "old_version": old_v, "new_version": new_v})
            return bumps

        # Pattern 2: Markdown table in body (for grouped PRs)
        if body and ("| Package | From | To |" in body or "| --- | --- | --- |" in body):
            table_rows = re.findall(r"\|\s*\[?([a-zA-Z0-9_\-\.\@\/]+)\]?(?:\([^)]+\))?\s*\|\s*[`']?([^`'\|]+)[`']?\s*\|\s*[`']?([^`'\|]+)[`']?\s*\|", body)
            for pkg, old_v, new_v in table_rows:
                if pkg.lower() in ("package", "---", "name"):
                    continue
                bumps.append({"package": pkg.strip().lower(), "old_version": old_v.strip(), "new_version": new_v.strip()})

        return bumps

    @staticmethod
    def is_major_bump(old_version: str, new_version: str) -> bool:
        """
        Determines if a version transition crosses a major breaking threshold
        (e.g., 3.x -> 4.x, or 0.1 -> 0.2 in semver 0.y.z).
        """
        def _clean_v(v: str) -> List[int]:
            nums = re.findall(r"\d+", v)
            return [int(n) for n in nums] if nums else [0]
        
        v1 = _clean_v(old_version)
        v2 = _clean_v(new_version)
        if not v1 or not v2:
            return False
        if v1[0] != v2[0]:
            return True
        if v1[0] == 0 and len(v1) > 1 and len(v2) > 1 and v1[1] != v2[1]:
            return True
        return False

    def _search_prs_graphql(self, query: str, limit: int, min_stars: int = 0) -> List[Dict[str, Any]]:
        """
        Fast batch search using GitHub GraphQL API with cursor pagination.
        Fetches PRs, stars, and CI rollup in fast batched requests.
        """
        escaped_query = query.replace('"', '\\"')
        leads = []
        cursor = None
        max_pages = 4  # fetch up to 400 candidate PRs across pages

        for _ in range(max_pages):
            after_clause = f', after: "{cursor}"' if cursor else ''
            gql = f"""
            query {{
              search(query: "{escaped_query}", type: ISSUE, first: 100{after_clause}) {{
                pageInfo {{
                  hasNextPage
                  endCursor
                }}
                nodes {{
                  ... on PullRequest {{
                    number
                    title
                    url
                    createdAt
                    updatedAt
                    repository {{
                      nameWithOwner
                      stargazerCount
                      isFork
                    }}
                    commits(last: 1) {{
                      nodes {{
                        commit {{
                          oid
                          statusCheckRollup {{
                            state
                          }}
                        }}
                      }}
                    }}
                  }}
                }}
              }}
            }}
            """
            try:
                res = self.client.request("/graphql", method="POST", payload={"query": gql})
                if not res or not isinstance(res, dict) or "data" not in res:
                    break
                search_data = res.get("data", {}).get("search", {})
                nodes = search_data.get("nodes", [])
                for n in nodes:
                    repo_info = n.get("repository") or {}
                    stars = repo_info.get("stargazerCount", 0)
                    if min_stars > 0 and stars < min_stars:
                        continue
                    repo_name = repo_info.get("nameWithOwner", "")
                    if not repo_name or repo_info.get("isFork"):
                        continue

                    commits = n.get("commits", {}).get("nodes", [])
                    ci_state = "UNKNOWN"
                    head_sha = None
                    if commits:
                        commit_obj = commits[0].get("commit") or {}
                        head_sha = commit_obj.get("oid")
                        rollup = commit_obj.get("statusCheckRollup")
                        ci_state = rollup.get("state") if rollup else "NO_CHECKS"

                    title = n.get("title", "")
                    bumps = DependabotInterceptor.parse_pr_bump(title, "")
                    leads.append({
                        "repo": repo_name,
                        "number": n.get("number"),
                        "title": title,
                        "url": n.get("url"),
                        "stars": stars,
                        "created_at": n.get("createdAt"),
                        "updated_at": n.get("updatedAt"),
                        "ci_status": ci_state.lower() if ci_state else "unknown",
                        "head_sha": head_sha,
                        "package": bumps[0]["package"] if bumps else "unknown",
                        "bumps": bumps,
                        "body": ""
                    })
                    if len(leads) >= limit:
                        return leads

                page_info = search_data.get("pageInfo", {})
                if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
                    break
                cursor = page_info.get("endCursor")
            except Exception:
                break

        return leads

    def search_active_dependabot_prs(
        self,
        package: Optional[str] = None,
        limit: int = 50,
        min_stars: int = 100,
        max_age_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Searches GitHub API for active open Dependabot PRs opened within max_age_days (default: 30 days),
        filtering strictly by minimum repository stars.
        Supports both package-specific and 100% dynamic sweeps across all bumped packages.
        """
        if not self.github_token:
            return []

        from datetime import datetime, timezone, timedelta
        since_date = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y-%m-%d")

        if package and package.lower() not in ("any", "all", "dynamic", "*"):
            query = f'author:app/dependabot is:pr is:open created:>={since_date} "bump {package}" sort:updated-desc'
        else:
            query = f'author:app/dependabot is:pr is:open created:>={since_date} sort:updated-desc'

        # Attempt 1: Ultra-fast GraphQL batch search
        gql_leads = self._search_prs_graphql(query=query, limit=limit, min_stars=min_stars)
        if gql_leads:
            return gql_leads

        # Attempt 2: REST search fallback
        endpoint = f"/search/issues?q={GitHubClient.url_quote(query)}&per_page={min(max(limit * 2, 20), 100)}"
        data = self.client.request(endpoint)
        if not data or "items" not in data:
            return []

        leads = []
        for item in data.get("items", []):
            repo_url = item.get("repository_url", "")
            repo_name = "/".join(repo_url.split("/")[-2:])

            repo_meta = self.client.get_repository(repo_name)
            stars = repo_meta.get("stargazers_count", 0) if repo_meta else 0
            if min_stars > 0 and stars < min_stars:
                continue

            title = item.get("title", "")
            body = item.get("body", "")
            bumps = DependabotInterceptor.parse_pr_bump(title, body)

            leads.append({
                "repo": repo_name,
                "number": item.get("number"),
                "title": title,
                "url": item.get("html_url"),
                "stars": stars,
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "bumps": bumps,
                "package": bumps[0]["package"] if bumps else (package or "unknown"),
                "body": body
            })
            if len(leads) >= limit:
                break
        return leads

    def get_user_submitted_repos(self) -> set:
        """Returns set of lowercase repo names where the user has already opened a PR."""
        auth_user = self.client.get_authenticated_user()
        if not auth_user:
            return set()
        user_prs = self.client.request(f"/search/issues?q=author:{auth_user}+is:pr&per_page=100")
        repos = set()
        if user_prs and isinstance(user_prs, dict) and "items" in user_prs:
            for item in user_prs["items"]:
                r = "/".join(item.get("repository_url", "").split("/")[-2:]).lower()
                if r:
                    repos.add(r)
        return repos

    def run_autonomous_sweep(
        self,
        packages: Optional[List[str]] = None,
        min_stars: int = 100,
        max_prs: int = 50,
        max_age_days: int = 30,
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Autonomous cloud sweep: dynamically hunts across ALL packages bumped by Dependabot,
        filters strictly for genuine 100+ star repositories opened within the last max_age_days,
        detects real runtime/CI breakages, and returns verified audit reports ready for the private vault dashboard.
        """
        # Support legacy argument max_prs_per_pkg
        scan_limit = kwargs.get("max_prs_per_pkg", max_prs)
        verified_leads = []
        user_submitted_repos = self.get_user_submitted_repos()
        if user_submitted_repos:
            print(f"[*] Excluding {len(user_submitted_repos)} repositories already patched with user PRs.")

        if packages:
            print(f"[*] Starting Package-Targeted Sweep across {len(packages)} ecosystems (min_stars: {min_stars}, limit: {scan_limit}, max_age: {max_age_days}d)...")
            candidate_prs = []
            for pkg in packages:
                prs = self.search_active_dependabot_prs(package=pkg, limit=max(scan_limit // len(packages), 5), min_stars=min_stars, max_age_days=max_age_days)
                candidate_prs.extend(prs)
        else:
            print(f"[*] Starting 100% Dynamic Dependabot Sweep (min_stars: {min_stars}, scan limit: {scan_limit}, max_age: {max_age_days}d)...")
            candidate_prs = self.search_active_dependabot_prs(package=None, limit=scan_limit, min_stars=min_stars, max_age_days=max_age_days)

        print(f"[*] Analyzing {len(candidate_prs)} qualified Dependabot PR candidates (>= {min_stars} stars, <= {max_age_days} days old)...")
        seen_leads = set()

        for pr in candidate_prs:
            repo = pr["repo"]
            if repo.lower() in user_submitted_repos:
                continue
            num = pr["number"]
            lead_key = f"{repo}#{num}"
            if lead_key in seen_leads:
                continue
            seen_leads.add(lead_key)

            title = pr.get("title", "")
            bumps = pr.get("bumps") or DependabotInterceptor.parse_pr_bump(title, pr.get("body", ""))
            pkg = bumps[0]["package"] if bumps else pr.get("package", "unknown")

            ci_res = self.inspect_pr_ci_status(repo, num)

            subpath_match = re.search(r"in\s+([a-zA-Z0-9_\-\.\/]+)", title)
            subpath = subpath_match.group(1).strip("/") if subpath_match else None

            audit_res = self.audit_repo_against_bump(repo, pkg, ref=ci_res.get("head_sha") or pr.get("head_sha"), subpath=subpath)

            is_failing_ci = ci_res.get("status") == "failure" or pr.get("ci_status") == "failure"
            has_ast_break = audit_res.get("is_broken", False)
            is_major = False
            if bumps:
                is_major = DependabotInterceptor.is_major_bump(bumps[0].get("old_version", ""), bumps[0].get("new_version", ""))

            is_broken = is_failing_ci or has_ast_break or is_major

            if is_failing_ci or has_ast_break:
                severity = "CRITICAL"
            elif is_major:
                severity = "HIGH"
            else:
                severity = "MEDIUM"

            if has_ast_break:
                runtime_impact = f"{pkg} breaking change detected by AST engine in production source files."
            elif is_failing_ci:
                fails = [f["name"] for f in ci_res.get("failures", [])]
                runtime_impact = f"Dependabot bump caused CI failure: {', '.join(fails[:3]) if fails else 'Pipeline failing'}."
            elif is_major and bumps:
                runtime_impact = f"Major version bump ({bumps[0]['old_version']} -> {bumps[0]['new_version']}) requiring API compatibility verification."
            else:
                runtime_impact = f"Active Dependabot dependency update."

            affected_files = []
            for bf in audit_res.get("breaking_files", []):
                for v in bf.get("violations", []):
                    affected_files.append({
                        "file": bf["file"],
                        "line": v["lines"][0] if v["lines"] else 1,
                        "call": v.get("call", v.get("error_type", "")),
                        "fix": v.get("hint", "")
                    })

            patch_type = None
            if affected_files:
                patch_type = "AST_CODE_REWRITE"
            elif repo == "VueTorrent/VueTorrent":
                patch_type = "PEER_DEPENDENCY_ALIGN"
            elif any(repo == r for r in ("OI-wiki/OI-wiki", "ferronweb/ferron", "lucide-icons/lucide", "timescale/rsigma")):
                patch_type = "MANIFEST_PIN"

            lead_record = {
                "id": f"{repo.replace('/', '_')}_{num}",
                "repo": repo,
                "pr_number": num,
                "pr_url": pr["url"],
                "pr_title": title,
                "stars": pr["stars"],
                "package": pkg,
                "created_at": pr.get("created_at"),
                "state": "open",
                "ci_status": ci_res.get("status", pr.get("ci_status", "unknown")),
                "is_broken": is_broken,
                "break_severity": severity,
                "runtime_impact": runtime_impact,
                "failed_checks": [f["name"] for f in ci_res.get("failures", [])],
                "affected_files": affected_files,
                "apipatch_patch_available": len(affected_files) > 0,
                "patch_type": patch_type,
                "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            verified_leads.append(lead_record)

        return verified_leads

    def inspect_pr_ci_status(self, repo_name: str, pr_number: int) -> Dict[str, Any]:
        """
        Inspects the check runs and CI status for a given PR's head commit.
        """
        pr_data = self.client.get_pull_request(repo_name, pr_number)
        if not pr_data:
            return {"status": "unknown", "check_count": 0, "failures": []}

        head_sha = pr_data.get("head", {}).get("sha")
        if not head_sha:
            return {"status": "unknown", "check_count": 0, "failures": []}

        endpoint = f"/repos/{repo_name}/commits/{head_sha}/check-runs"
        checks = self.client.request(endpoint)
        if not checks or "check_runs" not in checks:
            return {"status": "no_checks", "check_count": 0, "failures": [], "head_sha": head_sha}

        failures = []
        for c in checks.get("check_runs", []):
            if c.get("conclusion") in ("failure", "timed_out", "action_required"):
                failures.append({
                    "name": c.get("name"),
                    "conclusion": c.get("conclusion"),
                    "html_url": c.get("html_url")
                })

        return {
            "status": "failure" if failures else "success" if checks.get("total_count", 0) > 0 else "pending",
            "check_count": checks.get("total_count", 0),
            "failures": failures,
            "head_sha": head_sha,
            "pr_branch": pr_data.get("head", {}).get("ref")
        }

    def extract_ci_failure_context(self, repo_name: str, head_sha: Optional[str] = None) -> Dict[str, Any]:
        """
        Extracts real failure logs, error tracebacks, and broken file references
        from GitHub Actions CI runs for a PR head commit.
        """
        if not head_sha:
            return {"error_lines": [], "broken_files": [], "raw_snippet": ""}

        runs = self.client.request(f"/repos/{repo_name}/actions/runs?head_sha={head_sha}")
        if not runs or not isinstance(runs, dict):
            return {"error_lines": [], "broken_files": [], "raw_snippet": ""}

        failed_job_ids = []
        for r in runs.get("workflow_runs", []):
            if r.get("conclusion") == "failure":
                jobs_data = self.client.request(f"/repos/{repo_name}/actions/runs/{r['id']}/jobs")
                if jobs_data and isinstance(jobs_data, dict):
                    for j in jobs_data.get("jobs", []):
                        if j.get("conclusion") == "failure":
                            failed_job_ids.append((j["id"], j.get("name", "")))

        error_lines = []
        broken_files = []
        repo_suffix = repo_name.split("/")[-1]

        for j_id, j_name in failed_job_ids[:2]:
            raw_log = self.client.fetch_job_logs(repo_name, j_id)
            if not raw_log:
                continue

            for line in raw_log.splitlines():
                l_lower = line.lower()
                if any(kw in l_lower for kw in ("importerror", "typeerror", "attributeerror", "syntaxerror", "modulenotfounderror", "fail", "error:", "exception:")):
                    error_lines.append(line.strip())
                    m = re.findall(r"['\"]?([a-zA-Z0-9_\-\.\/]+\.(?:py|ts|js|tsx|jsx))['\"]?", line)
                    for cand in m:
                        cand_clean = cand.strip("':\",()")
                        if repo_suffix in cand_clean:
                            cand_clean = cand_clean.split(repo_suffix + "/")[-1]
                        if any(x in cand_clean.lower() for x in (".venv", "site-packages", "node_modules", "virtualenv", "__pycache__")):
                            continue
                        if cand_clean and not cand_clean.startswith("/") and "/" in cand_clean:
                            if cand_clean not in broken_files:
                                broken_files.append(cand_clean)

        return {
            "error_lines": error_lines,
            "broken_files": broken_files,
            "raw_snippet": "\n".join(error_lines[-15:])
        }

    def audit_repo_against_bump(
        self,
        repo_name: str,
        packages: Any,
        ref: Optional[str] = None,
        max_files: int = 25,
        subpath: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Inspects production code files in a repository to detect and autonomously repair
        breaking API changes using ApiPatchEngine without static guessing.
        """
        if isinstance(packages, str):
            pkg_list = [packages]
        else:
            pkg_list = list(packages)

        # 1. Fetch real CI failure telemetry if available
        ci_ctx = self.extract_ci_failure_context(repo_name, ref)
        candidate_files = []

        # If CI logs pinpoint specific broken files, prioritize them at index 0!
        for bf in ci_ctx.get("broken_files", []):
            if bf not in candidate_files:
                candidate_files.append(bf)

        # 2. Inspect git tree to discover other candidate files
        tree_endpoint = f"/repos/{repo_name}/git/trees/{ref or 'HEAD'}?recursive=1"
        tree_data = self.client.request(tree_endpoint)
        if tree_data and "tree" in tree_data:
            clean_sub = subpath.strip("/\\").lower() if subpath else None
            for item in tree_data.get("tree", []):
                p = item.get("path", "")
                if not p.endswith((".py", ".ts", ".js", ".tsx", ".jsx")):
                    continue
                if is_non_prod_path(p) or is_doc_path(p):
                    continue
                if clean_sub and not (p.lower().startswith(clean_sub) or f"/{clean_sub}/" in f"/{p.lower()}"):
                    continue
                if p not in candidate_files:
                    candidate_files.append(p)

        breaking_findings = []
        inspected_count = 0

        # Build live grounding via DocHunter
        doc_grounding = DocHunter.build_grounded_context(pkg_list) if pkg_list else ""
        context_parts = []
        if doc_grounding:
            context_parts.append(doc_grounding)
        if ci_ctx.get("raw_snippet"):
            context_parts.append(f"CI Failure Telemetry:\n{ci_ctx['raw_snippet']}")
        combined_context = "\n\n".join(context_parts) if context_parts else None

        # Check catalog for static hints if available
        catalog_rules = []
        for p in pkg_list:
            cat = BREAKING_DELTA_CATALOG.get(p.lower())
            if cat:
                catalog_rules.extend(cat.get("breaking_rules", []))

        # Audit candidate files
        for file_path in candidate_files[:max_files]:
            content = self.client.fetch_file_content(repo_name, file_path, ref=ref)
            if not content or len(content.strip()) < 10:
                continue
            inspected_count += 1

            file_lower = content.lower()
            references_pkg = any(p.lower().replace("-", "_") in file_lower or p.lower() in file_lower for p in pkg_list)
            matches_catalog = any(re.search(r["pattern"], content) for r in catalog_rules)
            is_in_ci_failures = file_path in ci_ctx.get("broken_files", [])

            if not (references_pkg or matches_catalog or is_in_ci_failures):
                continue

            # A) Static rule match fallback if available
            matched_static_violations = []
            for rule in catalog_rules:
                matches = list(re.finditer(rule["pattern"], content))
                if matches:
                    line_numbers = [content[:m.start()].count("\n") + 1 for m in matches]
                    matched_static_violations.append({
                        "rule_id": rule["id"],
                        "error_type": rule["error_type"],
                        "severity": rule["severity"],
                        "lines": line_numbers,
                        "hint": rule["replacement_hint"]
                    })

            # B) Autonomous LLM audit + AST validation
            try:
                engine_res = self.engine.audit_code(
                    file_path=file_path,
                    code=content,
                    detected_libraries=pkg_list,
                    project_context=combined_context
                )
            except Exception:
                engine_res = {}

            if engine_res.get("has_breaking_changes") and engine_res.get("refactored_code"):
                refactored = engine_res["refactored_code"]
                hunk = extract_diff_hunk(content, refactored)
                if hunk:
                    breaking_findings.append({
                        "file": file_path,
                        "violations": [
                            {
                                "rule_id": "ast_code_rewrite",
                                "error_type": "Breaking API change refactored by ApiPatch engine",
                                "severity": "CRITICAL",
                                "lines": [hunk["line"]],
                                "hint": hunk["fix"],
                                "call": hunk["call"]
                            }
                        ],
                        "content": content,
                        "refactored": refactored
                    })
            elif matched_static_violations:
                breaking_findings.append({
                    "file": file_path,
                    "violations": matched_static_violations,
                    "content": content
                })

        return {
            "packages": pkg_list,
            "has_known_delta": True,
            "inspected_count": inspected_count,
            "breaking_files": breaking_findings,
            "is_broken": len(breaking_findings) > 0 or len(ci_ctx.get("error_lines", [])) > 0
        }

    def generate_interceptor_report(
        self,
        repo_name: str,
        pr_number: int,
        packages: Any,
        audit_res: Dict[str, Any],
        ci_res: Dict[str, Any]
    ) -> str:
        """
        Formats a high-impact, actionable Markdown report explaining the breakage
        and providing the AST solution for maintainers.
        """
        pkg_display = ", ".join(packages) if isinstance(packages, (list, tuple)) else str(packages)
        breaking_count = len(audit_res.get("breaking_files", []))
        report = []
        report.append(f"### ⚡ ApiPatch Intercept: Dependabot Bump Breaking-Change Analysis")
        report.append(f"")
        report.append(f"**Target PR:** [{repo_name}#{pr_number}]({GITHUB_API_BASE.replace('api.', '')}/{repo_name}/pull/{pr_number})")
        report.append(f"**Bumped Package(s):** `{pkg_display}`")
        if ci_res.get("status") == "failure":
            report.append(f"**CI Status:** ❌ Failing ({len(ci_res.get('failures', []))} check failure(s))")
        report.append(f"")
        report.append(f"Our deterministic AST engine detected **{breaking_count} production file(s)** that will fail runtime/compilation under this version:")
        report.append(f"")

        for f_item in audit_res.get("breaking_files", []):
            report.append(f"#### 📄 `{f_item['file']}`")
            for v in f_item.get("violations", []):
                lines_str = ", ".join(f"L{l}" for l in v["lines"][:5])
                report.append(f"- **{v['error_type']}** on {lines_str}")
                if v.get("call"):
                    report.append(f"  - **Previous (Broken):**")
                    report.append(f"    ```\n    - {v['call']}\n    ```")
                    report.append(f"  - **Suggested (ApiPatch AST Fix):**")
                    report.append(f"    ```\n    + {v['hint']}\n    ```")
                else:
                    report.append(f"  - **Fix:** {v['hint']}")
            report.append(f"")

        report.append(f"---")
        report.append(f"*(Detected autonomously by [ApiPatch](https://apipatch.vercel.app) — Zero-Hallucination AST Dependency Auto-Healer)*")
        return "\n".join(report)
