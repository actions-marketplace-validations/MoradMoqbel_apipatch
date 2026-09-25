"""
Unit tests for ApiPatch Enterprise Codebase Health & Financial ROI Report Engine
"""

import os
import tempfile
import unittest
from apipatch.report import (
    CodebaseAuditor,
    format_terminal_report,
    generate_html_report,
    generate_markdown_report,
    DEPRECATION_RULES
)


class TestCodebaseAuditor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_audit_clean_directory(self):
        clean_file = os.path.join(self.temp_dir.name, "clean.py")
        with open(clean_file, "w", encoding="utf-8") as f:
            f.write("def add(a: int, b: int) -> int:\n    return a + b\n")

        auditor = CodebaseAuditor(target_dir=self.temp_dir.name, hourly_rate=100.0)
        metrics = auditor.run_audit()

        self.assertEqual(metrics["health_score"], 100)
        self.assertEqual(metrics["grade"], "A")
        self.assertEqual(metrics["total_findings"], 0)
        self.assertEqual(metrics["total_dev_hours_saved"], 0.0)
        self.assertEqual(metrics["payroll_saved"], 0.0)

    def test_audit_detects_langchain_and_anthropic_legacy(self):
        legacy_file = os.path.join(self.temp_dir.name, "agent.py")
        with open(legacy_file, "w", encoding="utf-8") as f:
            f.write(
                "from langchain.chains import LLMChain\n"
                "from anthropic import Anthropic\n"
                "client = Anthropic()\n"
                "res = client.completion(prompt='Human: Hello AI:')\n"
            )

        auditor = CodebaseAuditor(target_dir=self.temp_dir.name, hourly_rate=100.0)
        metrics = auditor.run_audit()

        self.assertGreater(metrics["total_findings"], 0)
        self.assertLess(metrics["health_score"], 100)
        self.assertIn("CRITICAL", metrics["severity_counts"])
        self.assertGreaterEqual(metrics["severity_counts"]["CRITICAL"], 2)
        # 12h for LC-001 + 12h for ANT-001 = 24h * $100/hr = $2,400 saved
        self.assertGreaterEqual(metrics["total_dev_hours_saved"], 24.0)
        self.assertGreaterEqual(metrics["payroll_saved"], 2400.0)

    def test_audit_detects_openai_and_pydantic_legacy(self):
        code_file = os.path.join(self.temp_dir.name, "models.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(
                "import openai\n"
                "from pydantic import BaseModel\n"
                "openai.api_key = 'sk-123'\n"
                "resp = openai.ChatCompletion.create(model='gpt-3.5-turbo', messages=[])\n"
                "class User(BaseModel):\n"
                "    class Config:\n"
                "        orm_mode = True\n"
            )

        auditor = CodebaseAuditor(target_dir=self.temp_dir.name, hourly_rate=75.0)
        metrics = auditor.run_audit()

        # Should detect OAI-001 (CRITICAL), OAI-002 (HIGH), and PYD-001 (HIGH)
        self.assertGreaterEqual(metrics["total_findings"], 3)
        self.assertIn("OpenAI", metrics["framework_counts"])
        self.assertIn("Pydantic", metrics["framework_counts"])
        self.assertLess(metrics["health_score"], 80)

    def test_html_report_generation(self):
        code_file = os.path.join(self.temp_dir.name, "test_app.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write("from langchain.chains import LLMChain\n")

        auditor = CodebaseAuditor(target_dir=self.temp_dir.name)
        metrics = auditor.run_audit()

        out_html = os.path.join(self.temp_dir.name, "report.html")
        generate_html_report(metrics, out_html)

        self.assertTrue(os.path.exists(out_html))
        with open(out_html, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("ApiPatch Monorepo Audit & ROI Report", content)
        self.assertIn("gauge-wrapper", content)
        self.assertIn("LLMChain", content)
        self.assertIn("badge-critical", content)

    def test_markdown_report_generation(self):
        code_file = os.path.join(self.temp_dir.name, "test_app.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write("from langchain.chains import LLMChain\n")

        auditor = CodebaseAuditor(target_dir=self.temp_dir.name)
        metrics = auditor.run_audit()

        out_md = os.path.join(self.temp_dir.name, "report.md")
        generate_markdown_report(metrics, out_md)

        self.assertTrue(os.path.exists(out_md))
        with open(out_md, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("# ⚡ ApiPatch Codebase Audit & ROI Report", content)
        self.assertIn("Executive Financial ROI Summary", content)
        self.assertIn("LLMChain", content)

    def test_terminal_report_output(self):
        auditor = CodebaseAuditor(target_dir=self.temp_dir.name)
        metrics = auditor.run_audit()
        terminal_text = format_terminal_report(metrics)

        self.assertIn("APIPATCH ENTERPRISE MONOREPO AUDIT & FINANCIAL ROI REPORT", terminal_text)
        self.assertIn("Codebase Health Score:", terminal_text)
        self.assertIn("Payroll Capital Saved:", terminal_text)


if __name__ == "__main__":
    unittest.main()
