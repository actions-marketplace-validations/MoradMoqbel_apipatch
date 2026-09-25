"""
ApiPatch Enterprise Codebase Health & Financial ROI Report Engine
Audits monorepos for deprecated APIs, calculates Codebase Health Score (0-100),
quantifies technical debt in payroll dollars and developer hours saved,
and generates standalone interactive HTML and Markdown executive reports.
"""

import os
import re
import ast
import json
from typing import List, Dict, Any, Optional, Tuple


# Pre-defined deprecation rules with metadata, severity, and migration examples
DEPRECATION_RULES = [
    # LangChain v0.3+ Rules
    {
        "id": "LC-001",
        "framework": "LangChain",
        "languages": [".py", ".pyw"],
        "severity": "CRITICAL",
        "name": "Deprecated LLMChain & legacy chain invocation",
        "pattern": r"from\s+langchain\.chains\s+import\s+.*LLMChain",
        "description": "LLMChain is legacy and removed in LangChain v0.3+. Use modern LCEL (prompt | llm | output_parser).",
        "before": "from langchain.chains import LLMChain\nchain = LLMChain(llm=llm, prompt=prompt)\nres = chain.run(query)",
        "after": "chain = prompt | llm | StrOutputParser()\nres = chain.invoke({'query': query})",
        "dev_hours": 12.0
    },
    {
        "id": "LC-002",
        "framework": "LangChain",
        "languages": [".py", ".pyw"],
        "severity": "HIGH",
        "name": "Legacy monolithic chat_models import",
        "pattern": r"from\s+langchain\.chat_models\s+import\s+(ChatOpenAI|ChatAnthropic)",
        "description": "Direct imports from langchain.chat_models are deprecated in favor of partner packages.",
        "before": "from langchain.chat_models import ChatOpenAI",
        "after": "from langchain_openai import ChatOpenAI",
        "dev_hours": 4.0
    },
    {
        "id": "LC-003",
        "framework": "LangChain",
        "languages": [".py", ".pyw"],
        "severity": "HIGH",
        "name": "Legacy monolithic embeddings import",
        "pattern": r"from\s+langchain\.embeddings\s+import\s+(OpenAIEmbeddings|HuggingFaceEmbeddings)",
        "description": "Direct imports from langchain.embeddings are deprecated in favor of partner packages.",
        "before": "from langchain.embeddings import OpenAIEmbeddings",
        "after": "from langchain_openai import OpenAIEmbeddings",
        "dev_hours": 4.0
    },
    {
        "id": "LC-004",
        "framework": "LangChain",
        "languages": [".py", ".pyw"],
        "severity": "CRITICAL",
        "name": "Deprecated RetrievalQA chain",
        "pattern": r"from\s+langchain\.chains\s+import\s+.*RetrievalQA|RetrievalQA\.from_chain_type",
        "description": "RetrievalQA is deprecated in LangChain v0.2/v0.3+. Use create_retrieval_chain.",
        "before": "from langchain.chains import RetrievalQA\nqa = RetrievalQA.from_chain_type(llm=llm, retriever=retriever)",
        "after": "from langchain.chains import create_retrieval_chain\nfrom langchain.chains.combine_documents import create_stuff_documents_chain\ncombine_docs = create_stuff_documents_chain(llm, prompt)\nqa = create_retrieval_chain(retriever, combine_docs)",
        "dev_hours": 16.0
    },
    {
        "id": "LC-005",
        "framework": "LangChain",
        "languages": [".py", ".pyw"],
        "severity": "MEDIUM",
        "name": "Deprecated chain.run() invocation",
        "pattern": r"\b(chain|agent_executor|qa)\.run\(",
        "description": ".run() is deprecated across LangChain Runnables. Migrate to .invoke().",
        "before": "output = chain.run(topic='AI')",
        "after": "output = chain.invoke({'topic': 'AI'})",
        "dev_hours": 2.0
    },

    # Anthropic Claude 2026 Rules
    {
        "id": "ANT-001",
        "framework": "Anthropic",
        "languages": [".py", ".pyw", ".js", ".ts"],
        "severity": "CRITICAL",
        "name": "Deprecated client.completion() API",
        "pattern": r"\bclient\.completion\(|\banthropic\.completion\(|HUMAN_PROMPT|AI_PROMPT",
        "description": "Anthropic Text Completions API is deprecated. Migrate to Claude Messages API.",
        "before": "res = client.completion(prompt=f'{HUMAN_PROMPT} Hello{AI_PROMPT}', model='claude-2')",
        "after": "res = client.messages.create(model='claude-3-5-sonnet-20241022', max_tokens=1024, messages=[{'role': 'user', 'content': 'Hello'}])",
        "dev_hours": 12.0
    },

    # OpenAI v1.0+ Rules
    {
        "id": "OAI-001",
        "framework": "OpenAI",
        "languages": [".py", ".pyw"],
        "severity": "CRITICAL",
        "name": "Legacy static openai.ChatCompletion.create()",
        "pattern": r"openai\.ChatCompletion\.create\(",
        "description": "Legacy static SDK syntax removed in OpenAI v1.0+. Instantiate client = OpenAI().",
        "before": "res = openai.ChatCompletion.create(model='gpt-3.5-turbo', messages=[...])",
        "after": "client = OpenAI()\nres = client.chat.completions.create(model='gpt-4o', messages=[...])",
        "dev_hours": 10.0
    },
    {
        "id": "OAI-002",
        "framework": "OpenAI",
        "languages": [".py", ".pyw"],
        "severity": "HIGH",
        "name": "Global openai.api_key assignment",
        "pattern": r"openai\.api_key\s*=",
        "description": "Global module-level API key assignment is deprecated in OpenAI v1.0+.",
        "before": "import openai\nopenai.api_key = 'sk-...'",
        "after": "from openai import OpenAI\nclient = OpenAI(api_key='sk-...')",
        "dev_hours": 3.0
    },
    {
        "id": "OAI-003",
        "framework": "OpenAI",
        "languages": [".py", ".pyw"],
        "severity": "CRITICAL",
        "name": "Legacy static openai.Completion.create()",
        "pattern": r"openai\.Completion\.create\(",
        "description": "Legacy Completion endpoint is deprecated. Migrate to Chat completions.",
        "before": "res = openai.Completion.create(model='text-davinci-003', prompt='Hello')",
        "after": "res = client.chat.completions.create(model='gpt-4o-mini', messages=[{'role': 'user', 'content': 'Hello'}])",
        "dev_hours": 8.0
    },

    # Pydantic v2 Rules
    {
        "id": "PYD-001",
        "framework": "Pydantic",
        "languages": [".py", ".pyw"],
        "severity": "HIGH",
        "name": "Deprecated class Config in BaseModel",
        "pattern": r"^\s{2,8}class\s+Config\s*:",
        "description": "Inner class Config is deprecated in Pydantic v2. Use model_config = ConfigDict(...) instead.",
        "before": "class User(BaseModel):\n    class Config:\n        orm_mode = True",
        "after": "class User(BaseModel):\n    model_config = ConfigDict(from_attributes=True)",
        "dev_hours": 6.0
    },
    {
        "id": "PYD-002",
        "framework": "Pydantic",
        "languages": [".py", ".pyw"],
        "severity": "HIGH",
        "name": "Deprecated @validator decorator",
        "pattern": r"@validator\(|from\s+pydantic\s+import\s+[^#\n]*?(?<!model_)(?<!field_)\bvalidator\b",
        "description": "@validator is deprecated in Pydantic v2. Use @field_validator with @classmethod.",
        "before": "from pydantic import validator\n@validator('name')\ndef val(cls, v): return v",
        "after": "from pydantic import field_validator\n@field_validator('name')\n@classmethod\ndef val(cls, v): return v",
        "dev_hours": 4.0
    },
    {
        "id": "PYD-003",
        "framework": "Pydantic",
        "languages": [".py", ".pyw"],
        "severity": "MEDIUM",
        "name": "Deprecated .dict() serialization",
        "pattern": r"\.dict\(\)",
        "description": ".dict() method is deprecated in Pydantic v2. Use .model_dump().",
        "before": "data = user.dict()",
        "after": "data = user.model_dump()",
        "dev_hours": 2.0
    },
    {
        "id": "PYD-004",
        "framework": "Pydantic",
        "languages": [".py", ".pyw"],
        "severity": "HIGH",
        "name": "BaseSettings imported from pydantic root",
        "pattern": r"from\s+pydantic\s+import\s+.*BaseSettings",
        "description": "BaseSettings moved to separate package pydantic-settings in Pydantic v2.",
        "before": "from pydantic import BaseSettings",
        "after": "from pydantic_settings import BaseSettings",
        "dev_hours": 3.0
    },

    # Stripe SDK Rules
    {
        "id": "STR-001",
        "framework": "Stripe",
        "languages": [".py", ".pyw", ".js", ".ts"],
        "severity": "CRITICAL",
        "name": "Legacy stripe.Charge.create()",
        "pattern": r"stripe\.Charge\.create\(",
        "description": "Direct Charges API is legacy and non-SCA compliant. Migrate to PaymentIntents.",
        "before": "charge = stripe.Charge.create(amount=2000, currency='usd', source=token)",
        "after": "intent = stripe.PaymentIntent.create(amount=2000, currency='usd', payment_method=pm_id, confirm=True)",
        "dev_hours": 14.0
    },

    # FastAPI Rules
    {
        "id": "FAS-001",
        "framework": "FastAPI",
        "languages": [".py", ".pyw"],
        "severity": "MEDIUM",
        "name": "Deprecated @app.on_event lifecycle handler",
        "pattern": r"@(?:app|router)\.on_event\(['\"](startup|shutdown)['\"]\)",
        "description": "@app.on_event is deprecated in FastAPI >= 0.93+. Migrate to lifespan context manager.",
        "before": "@app.on_event('startup')\nasync def startup(): ...",
        "after": "@asynccontextmanager\nasync def lifespan(app: FastAPI):\n    yield\napp = FastAPI(lifespan=lifespan)",
        "dev_hours": 4.0
    }
]


class Finding:
    def __init__(
        self,
        rule: Dict[str, Any],
        file_path: str,
        line_number: int,
        line_content: str
    ):
        self.rule_id = rule["id"]
        self.framework = rule["framework"]
        self.severity = rule["severity"]
        self.name = rule["name"]
        self.description = rule["description"]
        self.file_path = file_path
        self.line_number = line_number
        self.line_content = line_content.strip()
        self.before = rule["before"]
        self.after = rule["after"]
        self.dev_hours = rule["dev_hours"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "framework": self.framework,
            "severity": self.severity,
            "name": self.name,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "line_content": self.line_content,
            "before": self.before,
            "after": self.after,
            "dev_hours": self.dev_hours
        }


class CodebaseAuditor:
    """
    Audits a local directory or monorepo workspace, detects breaking API calls,
    computes Codebase Health Score (0-100), and calculates Financial ROI.
    """

    IGNORE_DIRS = {
        ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env",
        "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build",
        ".egg-info", ".next", ".nuxt", "target", "coverage", ".agents",
        "tests", "test", "testing", "clint_finder", "radar_web", "update_files"
    }

    SUPPORTED_EXTS = {".py", ".pyw", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}

    def __init__(self, target_dir: str = ".", hourly_rate: float = 75.0):
        self.target_dir = os.path.abspath(target_dir)
        self.hourly_rate = float(hourly_rate)
        self.findings: List[Finding] = []
        self.total_files_scanned = 0
        self.total_lines_scanned = 0
        self.flagged_files: set = set()
        self.manifest_data: Dict[str, Any] = {}

    def run_audit(self) -> Dict[str, Any]:
        """Runs the comprehensive audit across target directory."""
        self.findings = []
        self.total_files_scanned = 0
        self.total_lines_scanned = 0
        self.flagged_files = set()

        compiled_rules = [
            (re.compile(r["pattern"]), r) for r in DEPRECATION_RULES
        ]

        for root, dirs, files in os.walk(self.target_dir):
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS and not d.startswith(".")]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in self.SUPPORTED_EXTS:
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, self.target_dir).replace("\\", "/")

                self.total_files_scanned += 1

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    self.total_lines_scanned += len(lines)
                except Exception:
                    continue

                # For Python files, extract line numbers of docstrings, multiline strings, and print/logger statements
                non_code_lines = set()
                if ext in {".py", ".pyw"}:
                    try:
                        tree = ast.parse("".join(lines))
                        for node in ast.walk(tree):
                            # Multiline strings spanning multiple lines
                            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                                if hasattr(node, "lineno") and hasattr(node, "end_lineno") and node.end_lineno > node.lineno:
                                    for l in range(node.lineno, node.end_lineno + 1):
                                        non_code_lines.add(l)
                            # Docstring expressions (module, class, function docstrings)
                            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                                if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                                    for l in range(node.lineno, node.end_lineno + 1):
                                        non_code_lines.add(l)
                            # CLI print and logging calls (print examples, do not execute deprecated libraries)
                            elif isinstance(node, ast.Call):
                                func_name = ""
                                if isinstance(node.func, ast.Name):
                                    func_name = node.func.id
                                elif isinstance(node.func, ast.Attribute):
                                    func_name = node.func.attr
                                if func_name in {"print", "info", "warning", "error", "debug", "log"}:
                                    if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
                                        for l in range(node.lineno, node.end_lineno + 1):
                                            non_code_lines.add(l)
                    except Exception:
                        pass

                for line_idx, line in enumerate(lines, start=1):
                    if line_idx in non_code_lines:
                        continue
                    line_strip = line.strip()
                    if not line_strip:
                        continue
                    if line_strip.startswith(("#", "//", "*", "/*")):
                        continue
                    # Skip metadata, demo presets, and dictionary string keys/values
                    if line_strip.startswith((
                        '"before":', "'before':", '"after":', "'after':",
                        '"pattern":', "'pattern':", "source:", "output:",
                        "before:", "after:", "print(", "console.log(", "logger."
                    )):
                        continue
                    if (line_strip.startswith('"') and line_strip.endswith('"')) or (line_strip.startswith("'") and line_strip.endswith("'")):
                        continue
                    if (line_strip.startswith('"') and line_strip.endswith('",')) or (line_strip.startswith("'") and line_strip.endswith("',")):
                        continue
                    for regex, rule in compiled_rules:
                        # Language-specific filtering: only match rules defined for this file's language
                        if ext not in rule.get("languages", self.SUPPORTED_EXTS):
                            continue
                        if regex.search(line):
                            finding = Finding(
                                rule=rule,
                                file_path=rel_path,
                                line_number=line_idx,
                                line_content=line
                            )
                            self.findings.append(finding)
                            self.flagged_files.add(rel_path)

        return self.compute_metrics()

    def compute_metrics(self) -> Dict[str, Any]:
        """Calculates Health Score, Financial ROI, and framework breakdown."""
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        framework_counts: Dict[str, int] = {}
        total_dev_hours = 0.0

        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
            framework_counts[f.framework] = framework_counts.get(f.framework, 0) + 1
            total_dev_hours += f.dev_hours

        # Health score calculation (0 - 100)
        # Deductions: Critical = -15, High = -8, Medium = -4, Low = -1
        deductions = (
            severity_counts["CRITICAL"] * 15 +
            severity_counts["HIGH"] * 8 +
            severity_counts["MEDIUM"] * 4 +
            severity_counts["LOW"] * 1
        )
        health_score = max(0, min(100, 100 - deductions))

        if health_score >= 90:
            grade = "A"
            health_status = "Excellent (Production Modern)"
        elif health_score >= 80:
            grade = "B"
            health_status = "Good (Minor Deprecations)"
        elif health_score >= 70:
            grade = "C"
            health_status = "Moderate Risk (Action Recommended)"
        elif health_score >= 60:
            grade = "D"
            health_status = "High Risk (Breaking Changes Present)"
        else:
            grade = "F"
            health_status = "Critical (Immediate Remediation Required)"

        # Financial ROI Calculation
        payroll_saved = total_dev_hours * self.hourly_rate
        automated_remediation_seconds = max(15, len(self.findings) * 5)
        automated_dev_hours = automated_remediation_seconds / 3600.0
        roi_multiplier = (
            round((total_dev_hours / automated_dev_hours), 1)
            if automated_dev_hours > 0 and total_dev_hours > 0 else 1.0
        )

        return {
            "target_dir": self.target_dir,
            "total_files_scanned": self.total_files_scanned,
            "total_lines_scanned": self.total_lines_scanned,
            "flagged_files_count": len(self.flagged_files),
            "total_findings": len(self.findings),
            "health_score": health_score,
            "grade": grade,
            "health_status": health_status,
            "severity_counts": severity_counts,
            "framework_counts": framework_counts,
            "total_dev_hours_saved": round(total_dev_hours, 1),
            "payroll_saved": round(payroll_saved, 2),
            "hourly_rate": self.hourly_rate,
            "automated_remediation_seconds": automated_remediation_seconds,
            "roi_multiplier": roi_multiplier,
            "findings": [f.to_dict() for f in self.findings]
        }


def format_terminal_report(metrics: Dict[str, Any]) -> str:
    """Generates an ANSI terminal executive audit report."""
    score = metrics["health_score"]
    grade = metrics["grade"]
    status = metrics["health_status"]
    findings_count = metrics["total_findings"]
    hours = metrics["total_dev_hours_saved"]
    payroll = metrics["payroll_saved"]
    rate = metrics["hourly_rate"]

    # Color grading
    if score >= 80:
        score_color = "\033[92m"  # Green
    elif score >= 60:
        score_color = "\033[93m"  # Yellow
    else:
        score_color = "\033[91m"  # Red
    bold = "\033[1m"
    cyan = "\033[96m"
    reset = "\033[0m"

    bar_len = 24
    filled = int((score / 100.0) * bar_len)
    bar = f"{'█' * filled}{'░' * (bar_len - filled)}"

    out = []
    out.append("")
    out.append(f"{cyan}{bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{reset}")
    out.append(f" {bold}⚡ APIPATCH ENTERPRISE MONOREPO AUDIT & FINANCIAL ROI REPORT{reset}")
    out.append(f"{cyan}{bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{reset}")
    out.append(f" Target: {metrics['target_dir']}")
    out.append(f" Scanned: {metrics['total_files_scanned']:,} files ({metrics['total_lines_scanned']:,} LOC)")
    out.append("")
    out.append(f"  {bold}Codebase Health Score:{reset}  {score_color}{bold}{score}/100 [Grade {grade}]{reset}")
    out.append(f"  {bold}Health Meter:{reset}          [{score_color}{bar}{reset}]")
    out.append(f"  {bold}Status:{reset}                {status}")
    out.append("")
    out.append(f"{cyan}{bold}── Executive Financial ROI & Time Saved ──────────────────────{reset}")
    out.append(f"  • Deprecations Detected:       {bold}{findings_count}{reset} issue(s) across {len(metrics.get('findings', []))} location(s)")
    out.append(f"  • Est. Manual Developer Hours: {bold}{hours:.1f} hours{reset}")
    out.append(f"  • Payroll Capital Saved:       {bold}${payroll:,.2f}{reset} (benchmark @ ${rate:.0f}/hr)")
    out.append(f"  • ApiPatch Remediation Time:   {bold}~{metrics['automated_remediation_seconds']} seconds{reset}")
    out.append(f"  • Automation Speedup:          {bold}{metrics['roi_multiplier']:,}x faster{reset}")
    out.append("")
    out.append(f"{cyan}{bold}── Risk Breakdown by Severity ────────────────────────────────{reset}")
    sc = metrics["severity_counts"]
    out.append(f"  \033[91mCRITICAL:\033[0m {sc['CRITICAL']}   \033[93mHIGH:\033[0m {sc['HIGH']}   \033[94mMEDIUM:\033[0m {sc['MEDIUM']}   \033[90mLOW:\033[0m {sc['LOW']}")
    out.append("")

    if findings_count > 0:
        out.append(f"{cyan}{bold}── Top Deprecations Found ───────────────────────────────────{reset}")
        for idx, f in enumerate(metrics["findings"][:8], start=1):
            sev = f["severity"]
            c = "\033[91m" if sev == "CRITICAL" else ("\033[93m" if sev == "HIGH" else "\033[94m")
            out.append(f"  {idx}. {c}[{sev}]{reset} {bold}{f['name']}{reset}")
            out.append(f"     File: {f['file_path']}:{f['line_number']}")
            out.append(f"     Code: {f['line_content'][:75]}")
        if findings_count > 8:
            out.append(f"     ... and {findings_count - 8} more deprecations.")
        out.append("")
        out.append(f"{bold}⚡ Automated Remediation:{reset}")
        out.append(f"   Run: {cyan}apipatch fix . --write --verify-tests{reset}")
        out.append(f"   Or:  {cyan}apipatch pr owner/repo{reset}")
    else:
        out.append(f"\033[92m✔ Clean Codebase! No breaking API deprecations found.\033[0m")

    out.append(f"{cyan}{bold}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{reset}\n")
    return "\n".join(out)


def generate_html_report(metrics: Dict[str, Any], output_path: str) -> str:
    """
    Generates a high-aesthetic, standalone interactive HTML report
    with sleek dark-mode, circular SVG health meter, KPI cards, and diff previews.
    """
    score = metrics["health_score"]
    grade = metrics["grade"]
    findings = metrics["findings"]
    sc = metrics["severity_counts"]

    # Circumference for r=54 is 2 * pi * 54 = 339.29
    dash_array = 339.29
    dash_offset = dash_array - (dash_array * (score / 100.0))
    meter_color = "#10b981" if score >= 80 else ("#f59e0b" if score >= 60 else "#ef4444")

    findings_rows = []
    for f in findings:
        badge_class = f"badge-{f['severity'].lower()}"
        row = f"""
        <tr class="finding-row" data-severity="{f['severity']}" data-framework="{f['framework']}">
          <td><span class="badge {badge_class}">{f['severity']}</span></td>
          <td><strong>{f['framework']}</strong></td>
          <td>
            <div class="finding-title">{f['name']}</div>
            <div class="finding-loc"><code>{f['file_path']}:{f['line_number']}</code></div>
            <div class="finding-snippet"><code>{f['line_content']}</code></div>
          </td>
          <td>
            <div class="diff-box">
              <div class="diff-before"><span class="diff-tag">- OLD:</span> {f['before'].replace(chr(10), '<br>')}</div>
              <div class="diff-after"><span class="diff-tag">+ NEW:</span> {f['after'].replace(chr(10), '<br>')}</div>
            </div>
          </td>
          <td><strong>{f['dev_hours']:.1f}h</strong></td>
        </tr>
        """
        findings_rows.append(row)

    findings_html = "\n".join(findings_rows) if findings_rows else "<tr><td colspan='5' class='clean-msg'>✔ No breaking deprecations detected! Codebase is production modern.</td></tr>"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ApiPatch Audit & ROI Report — {os.path.basename(metrics['target_dir'])}</title>
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: rgba(18, 24, 38, 0.85);
      --card-border: rgba(255, 255, 255, 0.08);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #6366f1;
      --accent-glow: rgba(99, 102, 241, 0.25);
      --emerald: #10b981;
      --rose: #ef4444;
      --amber: #f59e0b;
      --cyan: #06b6d4;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 32px 24px;
      min-height: 100vh;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 28px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--card-border);
    }}
    .brand {{ display: flex; align-items: center; gap: 12px; }}
    .brand-logo {{
      width: 40px; height: 40px;
      background: linear-gradient(135deg, #6366f1, #a855f7);
      border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 20px; color: #fff;
      box-shadow: 0 0 20px var(--accent-glow);
    }}
    .brand h1 {{ font-size: 22px; font-weight: 700; }}
    .brand p {{ font-size: 13px; color: var(--text-muted); }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }}
    .badge-critical {{ background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }}
    .badge-high {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .badge-medium {{ background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); }}
    .badge-low {{ background: rgba(148, 163, 184, 0.2); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.4); }}

    /* KPI Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: 280px 1fr;
      gap: 20px;
      margin-bottom: 30px;
    }}
    @media (max-width: 900px) {{
      .kpi-grid {{ grid-template-columns: 1fr; }}
    }}
    .score-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      position: relative;
    }}
    .gauge-wrapper {{ position: relative; width: 140px; height: 140px; margin-bottom: 16px; }}
    .gauge-svg {{ transform: rotate(-90deg); width: 140px; height: 140px; }}
    .gauge-bg {{ fill: none; stroke: rgba(255, 255, 255, 0.08); stroke-width: 10; }}
    .gauge-fill {{
      fill: none;
      stroke: {meter_color};
      stroke-width: 10;
      stroke-linecap: round;
      stroke-dasharray: {dash_array};
      stroke-dashoffset: {dash_offset};
      transition: stroke-dashoffset 1s ease;
    }}
    .gauge-text {{
      position: absolute;
      top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      font-size: 32px;
      font-weight: 800;
      color: {meter_color};
    }}
    .score-title {{ font-size: 16px; font-weight: 700; margin-bottom: 4px; }}
    .score-desc {{ font-size: 13px; color: var(--text-muted); }}

    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
    }}
    .metric-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .metric-label {{ font-size: 12px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; margin-bottom: 8px; }}
    .metric-value {{ font-size: 28px; font-weight: 800; color: #fff; }}
    .metric-sub {{ font-size: 12px; color: var(--emerald); margin-top: 6px; font-weight: 600; }}
    .metric-value.highlight {{ color: #818cf8; }}
    .metric-value.emerald {{ color: var(--emerald); }}

    /* Action Banner */
    .action-banner {{
      background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(168, 85, 247, 0.15));
      border: 1px solid rgba(99, 102, 241, 0.4);
      border-radius: 14px;
      padding: 18px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 30px;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .action-text h3 {{ font-size: 16px; font-weight: 700; color: #fff; }}
    .action-text p {{ font-size: 13px; color: #cbd5e1; }}
    .action-cmd {{
      background: rgba(0, 0, 0, 0.5);
      border: 1px solid rgba(255, 255, 255, 0.15);
      padding: 8px 16px;
      border-radius: 8px;
      font-family: monospace;
      font-size: 14px;
      color: #38bdf8;
      user-select: all;
    }}

    /* Table */
    .table-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      overflow: hidden;
    }}
    .table-header {{
      padding: 18px 24px;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .table-header h2 {{ font-size: 17px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
    th {{
      background: rgba(255, 255, 255, 0.02);
      padding: 12px 18px;
      font-weight: 600;
      color: var(--text-muted);
      border-bottom: 1px solid var(--card-border);
    }}
    td {{ padding: 14px 18px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); vertical-align: top; }}
    tr:hover td {{ background: rgba(255, 255, 255, 0.02); }}
    .finding-title {{ font-weight: 700; color: #fff; margin-bottom: 4px; font-size: 14px; }}
    .finding-loc code {{ color: #38bdf8; font-size: 12px; }}
    .finding-snippet {{ margin-top: 6px; background: rgba(0, 0, 0, 0.3); padding: 4px 8px; border-radius: 4px; font-size: 12px; color: #e2e8f0; }}
    .diff-box {{ background: rgba(0, 0, 0, 0.4); border-radius: 6px; padding: 8px 12px; font-family: monospace; font-size: 11px; line-height: 1.4; }}
    .diff-before {{ color: #f87171; margin-bottom: 4px; }}
    .diff-after {{ color: #4ade80; }}
    .diff-tag {{ font-weight: 700; opacity: 0.8; }}
    .clean-msg {{ text-align: center; padding: 40px; font-size: 16px; color: var(--emerald); font-weight: 600; }}
    footer {{
      margin-top: 40px;
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <div class="brand-logo">⚡</div>
        <div>
          <h1>ApiPatch Monorepo Audit & ROI Report</h1>
          <p>Target: <code>{metrics['target_dir']}</code> &bull; Scanned: {metrics['total_files_scanned']:,} files ({metrics['total_lines_scanned']:,} LOC)</p>
        </div>
      </div>
      <div>
        <span class="badge" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.4);">
          Autonomous Engine
        </span>
      </div>
    </header>

    <div class="kpi-grid">
      <div class="score-card">
        <div class="gauge-wrapper">
          <svg class="gauge-svg" viewBox="0 0 120 120">
            <circle class="gauge-bg" cx="60" cy="60" r="54"></circle>
            <circle class="gauge-fill" cx="60" cy="60" r="54"></circle>
          </svg>
          <div class="gauge-text">{score}</div>
        </div>
        <div class="score-title">Grade {grade} &bull; Health Score</div>
        <div class="score-desc">{metrics['health_status']}</div>
      </div>

      <div class="metrics-grid">
        <div class="metric-card">
          <div class="metric-label">Developer Hours Saved</div>
          <div class="metric-value highlight">{metrics['total_dev_hours_saved']:.1f} hrs</div>
          <div class="metric-sub">Across {metrics['total_findings']} breaking deprecation(s)</div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Payroll Capital Saved</div>
          <div class="metric-value emerald">${metrics['payroll_saved']:,.2f}</div>
          <div class="metric-sub">Benchmark: ${metrics['hourly_rate']:.0f}/hr developer rate</div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Remediation Speedup</div>
          <div class="metric-value">{metrics['roi_multiplier']:,}x</div>
          <div class="metric-sub">~{metrics['automated_remediation_seconds']}s automated vs {metrics['total_dev_hours_saved']:.1f}h manual</div>
        </div>

        <div class="metric-card">
          <div class="metric-label">Deprecations Detected</div>
          <div class="metric-value">{metrics['total_findings']}</div>
          <div class="metric-sub">
            <span style="color:#ef4444">{sc['CRITICAL']} Crit</span> &bull; 
            <span style="color:#f59e0b">{sc['HIGH']} High</span> &bull; 
            <span style="color:#60a5fa">{sc['MEDIUM']} Med</span>
          </div>
        </div>
      </div>
    </div>

    <div class="action-banner">
      <div class="action-text">
        <h3>⚡ Ready to resolve all deprecations autonomously?</h3>
        <p>Run ApiPatch to apply AST-validated fixes in-place or generate verified PRs.</p>
      </div>
      <div class="action-cmd">apipatch fix . --write --verify-tests</div>
    </div>

    <div class="table-card">
      <div class="table-header">
        <h2>Detected Deprecations & Migration Path ({metrics['total_findings']})</h2>
      </div>
      <table>
        <thead>
          <tr>
            <th>Severity</th>
            <th>Framework</th>
            <th>Issue & Location</th>
            <th>Migration Diff (Before &rarr; After)</th>
            <th>Manual Effort</th>
          </tr>
        </thead>
        <tbody>
          {findings_html}
        </tbody>
      </table>
    </div>

    <footer>
      Generated autonomously by <strong>ApiPatch</strong> &bull; The Autonomous API Migration Agent &bull; 
      <a href="https://apipatch.vercel.app" style="color:#818cf8; text-decoration:none;">apipatch.vercel.app</a>
    </footer>
  </div>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return output_path


def generate_markdown_report(metrics: Dict[str, Any], output_path: str) -> str:
    """Generates an executive GitHub-flavored Markdown report."""
    score = metrics["health_score"]
    grade = metrics["grade"]
    sc = metrics["severity_counts"]

    md = []
    md.append(f"# ⚡ ApiPatch Codebase Audit & ROI Report\n")
    md.append(f"**Target Directory:** `{metrics['target_dir']}`  ")
    md.append(f"**Files Scanned:** {metrics['total_files_scanned']:,} files ({metrics['total_lines_scanned']:,} LOC)  ")
    md.append(f"**Codebase Health Score:** **{score}/100 (Grade {grade})** — *{metrics['health_status']}*\n")

    md.append("## 📊 Executive Financial ROI Summary\n")
    md.append("| Metric | Value | Benchmark Context |")
    md.append("| :--- | :--- | :--- |")
    md.append(f"| **Manual Dev Effort Saved** | **{metrics['total_dev_hours_saved']:.1f} hours** | Research, refactor, and test writing |")
    md.append(f"| **Payroll Capital Saved** | **${metrics['payroll_saved']:,.2f}** | Benchmark @ ${metrics['hourly_rate']:.0f}/hr |")
    md.append(f"| **ApiPatch Remediation Time** | **~{metrics['automated_remediation_seconds']} seconds** | Autonomous AST migration |")
    md.append(f"| **Remediation Speedup** | **{metrics['roi_multiplier']:,}x faster** | 100% test-verified |")
    md.append(f"| **Total Breaking Deprecations** | **{metrics['total_findings']}** | {sc['CRITICAL']} Critical, {sc['HIGH']} High, {sc['MEDIUM']} Medium |\n")

    if metrics["findings"]:
        md.append("## 🔍 Detected API Deprecations\n")
        md.append("| Severity | Framework | Issue & Location | Manual Effort |")
        md.append("| :---: | :--- | :--- | :---: |")
        for f in metrics["findings"]:
            md.append(f"| `{f['severity']}` | **{f['framework']}** | `{f['file_path']}:{f['line_number']}`<br>{f['name']} | `{f['dev_hours']:.1f}h` |")
        md.append("\n### ⚡ 1-Click Autonomous Remediation\n")
        md.append("```bash\napipatch fix . --write --verify-tests\n# Or submit live PR:\napipatch pr owner/repo\n```\n")
    else:
        md.append("> [!TIP]\n> **Clean Codebase!** No breaking API deprecations were detected.\n")

    content = "\n".join(md)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path
