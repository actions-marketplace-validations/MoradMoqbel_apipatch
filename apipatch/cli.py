"""
ApiPatch Command Line Interface (CLI)
Provides modern terminal commands for autonomous API code audits, automated refactoring,
sandbox test verification, live GitHub PR submission, and GitHub App Webhook daemon.
"""

import sys
import json
import socket
import argparse
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Enforce reasonable socket timeouts across all HTTP/TLS connections (120s for LLM generation)
socket.setdefaulttimeout(120)
from apipatch._version import __version__
from apipatch.engine import ApiPatchEngine, Colors
from apipatch.auto_detector import AutoDeprecationDetector
from apipatch.proactive_hunter import GitHubPRHunter
from apipatch.github_client import resolve_github_token, mask_token
from apipatch.webhook import run_webhook_server
from apipatch.telemetry import track_cli_event
from apipatch.report import (
    CodebaseAuditor,
    format_terminal_report,
    generate_html_report,
    generate_markdown_report
)


ONBOARDING_GUIDE = f"""
{Colors.HEADER}{Colors.BOLD}⚡ ApiPatch — Quick Setup Guide{Colors.ENDC}

{Colors.BOLD}Step 1: Get a free AI API key (choose one){Colors.ENDC}
  • Google Gemini (recommended, free tier):  https://aistudio.google.com/apikey
  • OpenAI:                                   https://platform.openai.com/api-keys
  • Anthropic Claude:                         https://console.anthropic.com/

{Colors.BOLD}Step 2: Set your key (choose one method){Colors.ENDC}

  {Colors.OKCYAN}Option A — .env file (recommended):{Colors.ENDC}
    Create a file named {Colors.BOLD}.env{Colors.ENDC} in your project directory:

      GEMINI_API_KEY=AIzaSy...
      # or
      OPENAI_API_KEY=sk-...
      # or
      ANTHROPIC_API_KEY=sk-ant-...

  {Colors.OKCYAN}Option B — Environment variable:{Colors.ENDC}
    export GEMINI_API_KEY="AIzaSy..."      # Linux/macOS
    set GEMINI_API_KEY=AIzaSy...           # Windows CMD
    $env:GEMINI_API_KEY="AIzaSy..."        # Windows PowerShell

  {Colors.OKCYAN}Option C — CLI flag:{Colors.ENDC}
    apipatch scan . --provider gemini --api-key AIzaSy...

{Colors.BOLD}Step 3: Run ApiPatch{Colors.ENDC}
  apipatch scan .                   # scan current directory
  apipatch fix . --write            # scan + apply fixes
  apipatch pr owner/repo --dry-run  # preview PR on any GitHub repo

{Colors.OKGREEN}Tip:{Colors.ENDC} Use {Colors.BOLD}--no-telemetry{Colors.ENDC} to disable anonymous usage reporting.
{Colors.OKGREEN}Docs:{Colors.ENDC} https://github.com/MoradMoqbel/apipatch
"""


def _check_provider_or_guide(engine: ApiPatchEngine, command: str) -> bool:
    """
    Checks if engine has an active AI provider.
    If not, prints the onboarding guide and returns False.
    """
    if engine.provider is not None:
        return True
    print(f"\n{Colors.FAIL}[!] No AI provider configured for '{command}' command.{Colors.ENDC}")
    print(ONBOARDING_GUIDE)
    return False

# Ensure UTF-8 console output on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        prog="apipatch",
        description=f"{Colors.HEADER}⚡ ApiPatch v{__version__} - Autonomous AI Agent for API Breaking Changes{Colors.ENDC}",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-v", "--version", action="version", version=f"apipatch {__version__}")
    parser.add_argument("--no-telemetry", action="store_true", help="Disable anonymous usage telemetry")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: scan
    scan_parser = subparsers.add_parser("scan", help="Scan a codebase for deprecated API signatures with smart pre-filtering")
    scan_parser.add_argument("path", nargs="?", default=".", help="File or directory path to scan (default: current dir)")
    scan_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "bedrock"], help="AI provider for dynamic reasoning")
    scan_parser.add_argument("--api-key", help="API key for chosen provider")
    scan_parser.add_argument("--model", help="Specific model name (e.g., gpt-4o, claude-3-5-sonnet, gemini-2.5-flash)")
    scan_parser.add_argument("-c", "--concurrency", type=int, default=6, help="Number of parallel worker threads (default: 6)")
    scan_parser.add_argument("-o", "--output", help="Save scan results as a JSON report to this file path")

    # Command: fix
    fix_parser = subparsers.add_parser("fix", help="Audit, refactor, and self-heal deprecated code")
    fix_parser.add_argument("path", nargs="?", default=".", help="File or directory path to refactor")
    fix_parser.add_argument("-w", "--write", action="store_true", help="Apply fixes in-place to files on disk")
    fix_parser.add_argument("--no-backup", action="store_true", help="Disable automatic .bak file creation when writing")
    fix_parser.add_argument("--verify-tests", "--run-tests", dest="verify_tests", action="store_true", help="Run project test suite (pytest/npm test) to verify fixes")
    fix_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "bedrock"], help="AI provider for dynamic reasoning")
    fix_parser.add_argument("--api-key", help="API key for chosen provider")
    fix_parser.add_argument("--model", help="Specific model name")
    fix_parser.add_argument("-c", "--concurrency", type=int, default=6, help="Number of parallel worker threads (default: 6)")
    fix_parser.add_argument("-o", "--output", help="Save fix results as a JSON report to this file path")

    # Command: pr (Autonomous GitHub Repository Audit & Live PR Submission)
    pr_parser = subparsers.add_parser("pr", help="Audit an entire GitHub repository and submit an autonomous live Pull Request")
    pr_parser.add_argument("repo", help="Target GitHub repository (e.g., owner/repo or https://github.com/owner/repo)")
    pr_parser.add_argument("--token", help="GitHub Personal Access Token (auto-discovered from github_token.txt or GITHUB_TOKEN if omitted)")
    pr_parser.add_argument("--branch", help="Target base branch on repository (default: repository default branch)")
    pr_parser.add_argument("--new-branch", help="Custom name for the migration branch to create")
    pr_parser.add_argument("--fork", dest="fork", action="store_true", default=None, help="Force forking the repository first")
    pr_parser.add_argument("--no-fork", dest="fork", action="store_false", help="Push directly to target repository without forking")
    pr_parser.add_argument("--dry-run", "--preview", dest="dry_run", action="store_true", help="Inspect and preview refactorings without pushing branch or PR")
    pr_parser.add_argument("--path", "--dir", "--target-path", dest="target_path", help="Target sub-directory or file path within repository to restrict audit/PR scope (e.g., 'beifong' or 'apps/my-app')")
    pr_parser.add_argument("--title", dest="custom_title", help="Custom title for the generated Pull Request")
    pr_parser.add_argument("--max-files", type=int, default=50, help="Max repository files to inspect (default: 50)")
    pr_parser.add_argument("--all", "--all-files", dest="all_files", action="store_true", help="Inspect all candidate files across the entire repository or target path without limit")
    pr_parser.add_argument("--files-per-subproject", type=int, default=None, help="In a Monorepo, inspect up to N entrypoint files per subproject across all workspaces")
    pr_parser.add_argument("--max-prs", type=int, default=1, help="Max separate PRs to open in a Monorepo across distinct subprojects (default: 1, prevents rate-limits and spam)")
    pr_parser.add_argument("--single-pr", dest="per_subproject", action="store_false", default=True, help="Combine all monorepo changes into a single PR instead of 1 PR per subproject")
    pr_parser.add_argument("--verify-tests", "--run-tests", dest="verify_tests", action="store_true", help="Run AST and sandbox test verification before opening PR")
    pr_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "bedrock"], help="AI provider for dynamic reasoning")
    pr_parser.add_argument("--api-key", help="API key for chosen provider")
    pr_parser.add_argument("--model", help="Specific model name")

    # Command: webhook (GitHub App Webhook Daemon)
    webhook_parser = subparsers.add_parser("webhook", help="Start the autonomous GitHub App Webhook daemon server")
    webhook_parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind to (default: 0.0.0.0)")
    webhook_parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    webhook_parser.add_argument("--token", help="GitHub Personal Access Token (auto-discovered from github_token.txt if omitted)")
    webhook_parser.add_argument("--secret", help="GitHub Webhook HMAC Secret (or GITHUB_WEBHOOK_SECRET env)")
    webhook_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "bedrock"], help="AI provider for dynamic reasoning")
    webhook_parser.add_argument("--api-key", help="API key for chosen provider")
    webhook_parser.add_argument("--model", help="Specific model name")

    # Command: detect
    detect_parser = subparsers.add_parser("detect", help="Auto-discover project dependencies and architecture context")
    detect_parser.add_argument("path", nargs="?", default=".", help="Project directory path (default: current dir)")

    # Command: hunt
    hunt_parser = subparsers.add_parser("hunt", help="Proactively search GitHub for deprecated code and submit PRs")
    hunt_parser.add_argument("query", nargs="?", default="openai.ChatCompletion.create language:python", help="GitHub Code Search query")
    hunt_parser.add_argument("--max", type=int, default=3, help="Max candidate repositories to inspect (default: 3)")
    hunt_parser.add_argument("--days", type=int, default=30, help="Only include repositories updated in the last N days (default: 30)")
    hunt_parser.add_argument("--all-time", dest="days", action="store_const", const=None, help="Disable recency filter and search all-time repositories")
    hunt_parser.add_argument("--min-stars", type=int, default=0, help="Minimum stars filter for candidate repositories (default: 0)")
    hunt_parser.add_argument("--token", help="GitHub Personal Access Token (auto-discovered if omitted)")
    hunt_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "bedrock"], help="AI provider for dynamic reasoning")
    hunt_parser.add_argument("--api-key", help="API key for chosen provider")
    hunt_parser.add_argument("--model", help="Specific model name")
    hunt_parser.add_argument("--submit", "--open-pr", dest="submit", action="store_true", help="Automatically submit live Pull Request to GitHub")
    hunt_parser.add_argument("--no-fork", dest="fork", action="store_false", default=True, help="Submit directly without forking (if repository write access is available)")

    # Command: discover (Smart Active Repository Discovery Engine)
    discover_parser = subparsers.add_parser("discover", help="Discover trending, active GitHub repositories and audit them for breaking changes")
    discover_parser.add_argument("query", nargs="?", default="topic:ai language:python", help="GitHub search topic or query (default: 'topic:ai language:python')")
    discover_parser.add_argument("--days", type=int, default=30, help="Max days since last update (default: 30)")
    discover_parser.add_argument("--min-stars", type=int, default=10, help="Minimum star count (default: 10)")
    discover_parser.add_argument("--max-repos", type=int, default=3, help="Max repositories to audit (default: 3)")
    discover_parser.add_argument("--token", help="GitHub Personal Access Token (auto-discovered if omitted)")
    discover_parser.add_argument("--provider", choices=["openai", "anthropic", "gemini", "bedrock"], help="AI provider for dynamic reasoning")
    discover_parser.add_argument("--api-key", help="API key for chosen provider")
    discover_parser.add_argument("--model", help="Specific model name")
    discover_parser.add_argument("--submit", "--open-pr", dest="submit", action="store_true", help="Submit live Pull Requests directly")
    discover_parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Preview PRs without opening (default: True)")

    # Command: radar
    radar_parser = subparsers.add_parser("radar", help="Launch the local interactive ApiPatch Radar Web Dashboard")
    radar_parser.add_argument("--port", type=int, default=8765, help="Port to bind dashboard server (default: 8765)")
    radar_parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    # Command: report (Enterprise Monorepo Audit & Financial ROI Report)
    report_parser = subparsers.add_parser("report", help="Audit monorepo health score (0-100) and quantify payroll ROI saved")
    report_parser.add_argument("path", nargs="?", default=".", help="Directory or monorepo workspace to audit (default: current dir)")
    report_parser.add_argument("--format", choices=["terminal", "html", "md", "json", "all"], default="all", help="Output report format (default: all)")
    report_parser.add_argument("-o", "--output", help="Custom output report file path (e.g., apipatch_audit_report.html)")
    report_parser.add_argument("--hourly-rate", type=float, default=75.0, help="Benchmark developer hourly rate in USD (default: $75.00)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if getattr(args, "no_telemetry", False):
        import os
        os.environ["APIPATCH_NO_TELEMETRY"] = "1"

    track_cli_event(args.command, {"has_provider": bool(getattr(args, "provider", None))})

    if args.command == "scan":
        engine = ApiPatchEngine(
            provider_name=args.provider,
            api_key=args.api_key,
            model=args.model,
            create_backup=False,
            concurrency=getattr(args, "concurrency", 6)
        )
        if not _check_provider_or_guide(engine, "scan"):
            sys.exit(0)
        if os_is_file(args.path):
            result = engine.process_file(args.path, write_in_place=False)
            if getattr(args, "output", None):
                _save_report({"results": [result]}, args.output)
        else:
            result = engine.process_directory(args.path, write_in_place=False)
            if getattr(args, "output", None):
                _save_report(result, args.output)

    elif args.command == "fix":
        engine = ApiPatchEngine(
            provider_name=args.provider,
            api_key=args.api_key,
            model=args.model,
            create_backup=not args.no_backup,
            concurrency=getattr(args, "concurrency", 6),
            verify_tests=getattr(args, "verify_tests", False)
        )
        if not _check_provider_or_guide(engine, "fix"):
            sys.exit(0)
        if os_is_file(args.path):
            result = engine.process_file(
                args.path,
                write_in_place=args.write,
                verify_tests=args.verify_tests
            )
            if getattr(args, "output", None):
                _save_report({"results": [result]}, args.output)
        else:
            result = engine.process_directory(
                args.path,
                write_in_place=args.write,
                verify_tests=args.verify_tests
            )
            if getattr(args, "output", None):
                _save_report(result, args.output)

    elif args.command == "pr":
        engine = ApiPatchEngine(
            provider_name=args.provider,
            api_key=args.api_key,
            model=args.model,
            create_backup=False,
            verify_tests=getattr(args, "verify_tests", False)
        )
        if not _check_provider_or_guide(engine, "pr"):
            sys.exit(1)
        hunter = GitHubPRHunter(github_token=args.token, engine=engine)
        hunter.audit_and_pr_repository(
            repo_name=args.repo,
            fork=args.fork,
            base_branch=args.branch,
            branch_name=args.new_branch,
            submit=not args.dry_run,
            dry_run=args.dry_run,
            max_files=0 if getattr(args, "all_files", False) else args.max_files,
            target_path=getattr(args, "target_path", None),
            custom_title=getattr(args, "custom_title", None),
            verify_tests=getattr(args, "verify_tests", False),
            per_subproject=getattr(args, "per_subproject", True),
            max_prs=getattr(args, "max_prs", 1),
            files_per_subproject=getattr(args, "files_per_subproject", None)
        )

    elif args.command == "webhook":
        engine = ApiPatchEngine(
            provider_name=args.provider,
            api_key=args.api_key,
            model=args.model,
            create_backup=False
        )
        run_webhook_server(
            host=args.host,
            port=args.port,
            token=args.token,
            secret=args.secret,
            engine=engine
        )

    elif args.command == "detect":
        detector = AutoDeprecationDetector(target_dir=args.path)
        detector.run_autonomous_discovery()

    elif args.command == "hunt":
        engine = ApiPatchEngine(
            provider_name=args.provider,
            api_key=args.api_key,
            model=args.model,
            create_backup=False
        )
        if not _check_provider_or_guide(engine, "hunt"):
            sys.exit(1)
        hunter = GitHubPRHunter(github_token=args.token, engine=engine)
        hunter.hunt_and_preview(
            query=args.query,
            max_results=args.max,
            recent_days=args.days,
            min_stars=getattr(args, "min_stars", 0),
            submit=getattr(args, "submit", False),
            fork=getattr(args, "fork", True)
        )

    elif args.command == "discover":
        engine = ApiPatchEngine(
            provider_name=args.provider,
            api_key=args.api_key,
            model=args.model,
            create_backup=False
        )
        if not _check_provider_or_guide(engine, "discover"):
            sys.exit(1)
        hunter = GitHubPRHunter(github_token=args.token, engine=engine)
        dry_run = not getattr(args, "submit", False)
        hunter.discover_and_audit(
            query=args.query,
            days=args.days,
            min_stars=args.min_stars,
            max_repos=args.max_repos,
            dry_run=dry_run
        )

    elif args.command == "radar":
        from radar_server import run_server
        run_server(port=args.port, auto_open=not args.no_browser)

    elif args.command == "report":
        import os
        import json
        auditor = CodebaseAuditor(target_dir=args.path, hourly_rate=args.hourly_rate)
        metrics = auditor.run_audit()

        terminal_text = format_terminal_report(metrics)
        print(terminal_text)

        fmt = args.format.lower()
        base_name = "apipatch_audit_report"

        if fmt in ("html", "all"):
            out_file = args.output if (args.output and args.output.endswith(".html")) else f"{base_name}.html"
            generate_html_report(metrics, out_file)
            print(f"{Colors.OKGREEN}[✓] Standalone HTML report generated → {os.path.abspath(out_file)}{Colors.ENDC}")

        if fmt in ("md", "all"):
            out_file = args.output if (args.output and args.output.endswith(".md")) else f"{base_name}.md"
            generate_markdown_report(metrics, out_file)
            print(f"{Colors.OKGREEN}[✓] Executive Markdown report generated → {os.path.abspath(out_file)}{Colors.ENDC}")

        if fmt in ("json", "all"):
            out_file = args.output if (args.output and args.output.endswith(".json")) else f"{base_name}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(metrics, f, indent=2)
            print(f"{Colors.OKGREEN}[✓] Machine-readable JSON report generated → {os.path.abspath(out_file)}{Colors.ENDC}")



def os_is_file(path: str) -> bool:
    import os
    return os.path.isfile(path)


def _save_report(data: dict, output_path: str) -> None:
    """Saves the scan/fix result as a JSON report file."""
    import os
    import datetime
    report = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "apipatch_version": __version__,
        "total_scanned": data.get("total_scanned", len(data.get("results", []))),
        "affected_files": data.get("affected_files", 0),
        "results": [
            {
                "file": r.get("file", ""),
                "status": r.get("status", ""),
                "issues": r.get("issues", [])
            }
            for r in data.get("results", [])
        ]
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"{Colors.OKGREEN}[✓] Report saved → {os.path.abspath(output_path)}{Colors.ENDC}")


if __name__ == "__main__":
    main()
