"""
ApiPatch GitHub App & Webhook Daemon Server
Listens for GitHub Webhook events (push, pull_request, installation),
verifies HMAC-SHA256 signatures, and autonomously triggers the ApiPatch
refactoring and PR submission engine in the background.
"""

import os
import sys
import re
import json
import hmac
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, Set
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from apipatch._version import __version__
from apipatch.github_client import resolve_github_token, mask_token
from apipatch.proactive_hunter import GitHubPRHunter
from apipatch.engine import ApiPatchEngine, Colors

_RE_VALID_REPO = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")
_ACTIVE_AUDITS: Set[str] = set()
_AUDIT_LOCK = threading.Lock()
_WEBHOOK_WORKER_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="apipatch-webhook")


def verify_signature(payload_bytes: bytes, signature_header: Optional[str], secret: Optional[str]) -> bool:
    """
    Validates the GitHub Webhook HMAC-SHA256 signature (X-Hub-Signature-256).
    If secret is not set, returns True (open dev mode).
    """
    if not secret:
        return True
    if not signature_header:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    received_sig = signature_header[len(prefix):]
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(received_sig, expected_sig)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP Server for concurrent webhook event handling."""
    daemon_threads = True


class ApiPatchWebhookHandler(BaseHTTPRequestHandler):
    """
    Handles incoming HTTP GET and POST requests for GitHub Webhooks.
    """
    server_version = f"ApiPatch-GitHubApp/{__version__}"

    def do_GET(self):
        """Health check endpoint."""
        if self.path in ("/", "/health", "/ping"):
            self._send_json(200, {
                "status": "healthy",
                "service": "ApiPatch Autonomous GitHub App",
                "version": __version__,
                "authenticated": bool(self.server.hunter.github_token)
            })
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        """Processes incoming GitHub Webhook events."""
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        # 1. Verify HMAC Signature
        sig_header = self.headers.get("X-Hub-Signature-256")
        secret = self.server.webhook_secret
        if not verify_signature(raw_body, sig_header, secret):
            print(f"{Colors.FAIL}[!] Webhook signature verification failed.{Colors.ENDC}")
            self._send_json(401, {"error": "Invalid webhook HMAC signature"})
            return

        # 2. Parse Payload
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        event = self.headers.get("X-GitHub-Event", "ping")
        print(f"\n{Colors.OKCYAN}[Webhook] Received GitHub event: '{event}'{Colors.ENDC}")

        # 3. Dispatch Event
        if event == "ping":
            self._send_json(200, {
                "status": "pong",
                "message": "ApiPatch GitHub App connection active",
                "zen": payload.get("zen", "Code with confidence.")
            })

        elif event == "push":
            ref = payload.get("ref", "")
            repo_data = payload.get("repository", {})
            repo_name = repo_data.get("full_name", "")

            # Prevent recursive loop: do not process commits pushed by ApiPatch branch
            if "apipatch" in ref.lower():
                print(f"[Webhook] Ignoring push from ApiPatch branch ({ref}).")
                self._send_json(200, {"status": "ignored", "reason": "Self-triggered push"})
                return

            if not repo_name or not _RE_VALID_REPO.match(repo_name):
                self._send_json(400, {"error": "Invalid repository full_name format. Expected 'owner/repo'."})
                return

            if not isinstance(ref, str) or len(ref) > 200:
                self._send_json(400, {"error": "Invalid ref parameter."})
                return

            # Deduplication check: prevent multiple concurrent audits for the same repository
            with _AUDIT_LOCK:
                if repo_name in _ACTIVE_AUDITS:
                    print(f"[Webhook] Audit already in progress for {repo_name}. Skipping duplicate push trigger.")
                    self._send_json(200, {
                        "status": "skipped",
                        "reason": "Audit already in progress for this repository",
                        "repo": repo_name
                    })
                    return
                _ACTIVE_AUDITS.add(repo_name)

            print(f"{Colors.OKGREEN}[Webhook] Triggering autonomous audit for push on {repo_name} ({ref})...{Colors.ENDC}")

            # Schedule in bounded worker pool to respond to GitHub immediately (< 10s timeout)
            _WEBHOOK_WORKER_POOL.submit(self._run_async_pipeline, repo_name, None)

            self._send_json(202, {
                "status": "accepted",
                "event": "push",
                "repo": repo_name,
                "ref": ref,
                "message": "Autonomous audit and Pull Request pipeline scheduled"
            })

        elif event in ("installation", "installation_repositories"):
            account = payload.get("installation", {}).get("account", {}).get("login", "User")
            action = payload.get("action", "")
            print(f"{Colors.OKGREEN}[Webhook] ApiPatch GitHub App installed for @{account} (action: {action}){Colors.ENDC}")
            self._send_json(200, {
                "status": "welcomed",
                "account": account,
                "action": action
            })

        elif event == "pull_request":
            action = payload.get("action", "")
            pr_data = payload.get("pull_request", {})
            pr_title = pr_data.get("title", "")
            pr_url = pr_data.get("html_url", "")
            print(f"[Webhook] PR {action}: {pr_title} ({pr_url})")
            self._send_json(200, {
                "status": "recorded",
                "action": action,
                "pr_url": pr_url
            })

        else:
            self._send_json(200, {"status": "unhandled_event", "event": event})

    def _run_async_pipeline(self, repo_name: str, base_branch: Optional[str] = None):
        """Asynchronously runs ApiPatch engine and submits PR, then releases active lock."""
        try:
            hunter: GitHubPRHunter = self.server.hunter
            hunter.audit_and_pr_repository(
                repo_name=repo_name,
                base_branch=base_branch,
                submit=True
            )
        except Exception as e:
            print(f"{Colors.FAIL}[!] Webhook background pipeline error for {repo_name}: {e}{Colors.ENDC}")
        finally:
            with _AUDIT_LOCK:
                _ACTIVE_AUDITS.discard(repo_name)

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        """Helper to send structured JSON HTTP response."""
        response_bytes = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, format, *args):
        """Silence standard Apache style logging to keep terminal clean."""
        return


def run_webhook_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    token: Optional[str] = None,
    secret: Optional[str] = None,
    engine: Optional[ApiPatchEngine] = None
) -> None:
    """
    Starts the live GitHub App Webhook daemon server.
    """
    resolved_token = resolve_github_token(token)
    webhook_secret = secret or os.getenv("GITHUB_WEBHOOK_SECRET")

    hunter = GitHubPRHunter(github_token=resolved_token, engine=engine)
    server_address = (host, port)
    httpd = ThreadedHTTPServer(server_address, ApiPatchWebhookHandler)
    httpd.hunter = hunter
    httpd.webhook_secret = webhook_secret

    auth_user = hunter.get_authenticated_user()
    print(f"\n{Colors.HEADER}{Colors.BOLD}╔══════════════════════════════════════════════════════════════════╗{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}║         ⚡ ApiPatch Autonomous GitHub App Webhook Server        ║{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}╚══════════════════════════════════════════════════════════════════╝{Colors.ENDC}")
    print(f"  • Version:        {Colors.BOLD}v{__version__}{Colors.ENDC}")
    print(f"  • Listening On:   {Colors.OKCYAN}http://{host}:{port}{Colors.ENDC}")
    print(f"  • Webhook Path:   {Colors.OKCYAN}http://{host}:{port}/webhook{Colors.ENDC}")
    print(f"  • Auth User:      {Colors.OKGREEN}@{auth_user if auth_user else 'None'}{Colors.ENDC} ({mask_token(resolved_token)})")
    print(f"  • HMAC Secret:    {Colors.OKGREEN}Active{Colors.ENDC}" if webhook_secret else f"  • HMAC Secret:    {Colors.WARNING}None (open mode){Colors.ENDC}")
    print(f"\n{Colors.OKGREEN}[✓] Webhook daemon is ready to receive GitHub push and PR events...{Colors.ENDC}\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}[*] Stopping ApiPatch Webhook Server...{Colors.ENDC}")
        httpd.server_close()
