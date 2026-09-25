"""
Unit tests for Deep Symbol Verification & Ephemeral Micro-Sandbox Engine
"""

import unittest
from apipatch.test_runner import MicroSandboxEvaluator
from apipatch.doc_hunter import DocHunter
from apipatch.validator import CodeValidator


class TestMicroSandbox(unittest.TestCase):
    def test_doc_hunter_rejects_cross_package_tool_context_on_genai_types(self):
        # ToolContext belongs to google.adk.tools, NOT google.genai.types
        self.assertFalse(DocHunter.verify_module_symbol("google.genai.types", "ToolContext"))
        self.assertFalse(DocHunter.verify_module_symbol("google.genai.types", "SessionContext"))
        self.assertTrue(DocHunter.verify_module_symbol("google.genai.types", "GenerateContentConfig"))
        self.assertTrue(DocHunter.verify_module_symbol("google.genai.types", "Part"))

    def test_micro_sandbox_evaluates_valid_builtins_and_stdlib(self):
        valid_code = """
import os
import sys
from pathlib import Path

def get_path():
    return Path(os.getcwd())
"""
        res = MicroSandboxEvaluator.evaluate_code_imports(valid_code)
        self.assertTrue(res.is_valid)

    def test_micro_sandbox_rejects_fake_attributes_on_stdlib_or_installed_modules(self):
        invalid_code = """
import os
import sys

def broken():
    return os.FakeNonExistentMethod12345()
"""
        res = MicroSandboxEvaluator.evaluate_code_imports(invalid_code)
        self.assertFalse(res.is_valid)
        self.assertIn("FakeNonExistentMethod12345", res.error_message)

    def test_validator_rejects_hallucinated_tool_context_on_genai_types(self):
        orig_code = """
from google.adk.tools import ToolContext
from google.genai import types

async def generate_chart(tool_context: ToolContext):
    pass
"""
        bad_refactored = """
from google.genai import types

async def generate_chart(tool_context: types.ToolContext):
    pass
"""
        val = CodeValidator.validate(orig_code, bad_refactored, file_extension=".py")
        self.assertFalse(val.is_valid)
        self.assertIn("ToolContext", val.error_message)

    def test_validator_accepts_valid_types_symbols(self):
        orig_code = """
from google.genai import types

def configure():
    pass
"""
        good_refactored = """
from google.genai import types

def configure():
    cfg = types.GenerateContentConfig(response_modalities=["TEXT"])
    return cfg
"""
        val = CodeValidator.validate(orig_code, good_refactored, file_extension=".py")
        self.assertTrue(val.is_valid)

    def test_micro_sandbox_safe_against_malicious_injections(self):
        # Code containing syntax-valid but maliciously named constructs
        malicious_code = """
import os
def attack():
    pass
"""
        res = MicroSandboxEvaluator.evaluate_code_imports(malicious_code)
        self.assertTrue(res.is_valid)


if __name__ == "__main__":
    unittest.main()
