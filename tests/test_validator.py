"""
Unit tests for CodeValidator
"""

import unittest
from apipatch.validator import CodeValidator


class TestCodeValidator(unittest.TestCase):
    def test_valid_python_syntax(self):
        valid_code = """
import os

def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def __init__(self, greeting: str):
        self.greeting = greeting
"""
        result = CodeValidator.validate_python_syntax(valid_code)
        self.assertTrue(result.is_valid)

    def test_invalid_python_syntax(self):
        invalid_code = """
def broken_function(:
    return 123
"""
        result = CodeValidator.validate_python_syntax(invalid_code)
        self.assertFalse(result.is_valid)
        self.assertIsNotNone(result.error_line)

    def test_business_logic_preservation(self):
        orig = """
def calculate_tax(amount):
    return amount * 0.15

class UserAccount:
    pass
"""
        refactored_good = """
def calculate_tax(amount):
    return amount * 0.15

class UserAccount:
    pass
"""
        refactored_bad = """
def different_func():
    pass
"""
        res_good = CodeValidator.validate_business_logic_preservation(orig, refactored_good)
        self.assertTrue(res_good.is_valid)

        res_bad = CodeValidator.validate_business_logic_preservation(orig, refactored_bad)
        self.assertFalse(res_bad.is_valid)
        self.assertIn("calculate_tax", res_bad.error_message)

    def test_framework_runner_preservation(self):
        orig = """
from google.adk.runners import InMemoryRunner

class Orchestrator:
    def __init__(self, agent):
        self.runner = InMemoryRunner(agent=agent)
"""
        # Refactored code that dropped InMemoryRunner
        refactored_bad = """
import google.generative_ai as genai

class Orchestrator:
    def __init__(self, agent):
        self.model = genai.GenerativeModel("gemini")
"""
        res = CodeValidator.validate_business_logic_preservation(orig, refactored_bad)
        self.assertFalse(res.is_valid)
        self.assertIn("InMemoryRunner", res.error_message)

    def test_hallucinated_import_detection(self):
        bad_code = "from python_dotenv import load_dotenv\nload_dotenv()"
        res = CodeValidator.validate_python_syntax(bad_code)
        self.assertFalse(res.is_valid)
        self.assertIn("python_dotenv", res.error_message)

    def test_docstring_preservation(self):
        orig_with_doc = '"""Module documentation for tools."""\ndef my_tool():\n    return 1\n'
        ref_without_doc = 'def my_tool():\n    return 1\n'
        ref_with_doc = '"""Module documentation for tools."""\ndef my_tool():\n    return 2\n'

        res_bad = CodeValidator.validate_business_logic_preservation(orig_with_doc, ref_without_doc)
        self.assertFalse(res_bad.is_valid)
        self.assertIn("docstring", res_bad.error_message.lower())

        res_good = CodeValidator.validate_business_logic_preservation(orig_with_doc, ref_with_doc)
        self.assertTrue(res_good.is_valid)

    def test_js_symbol_preservation(self):
        orig_js = "export function processUser(user) { return user.name; }\nexport const calculateTotal = () => 100;"
        bad_js = "export function otherFunction() { return 123; }"
        good_js = "export function processUser(user) { return user.name.toUpperCase(); }\nexport const calculateTotal = () => 100;"

        res_bad = CodeValidator.validate_generic_integrity(orig_js, bad_js)
        self.assertFalse(res_bad.is_valid)
        self.assertIn("processUser", res_bad.error_message)

        res_good = CodeValidator.validate_generic_integrity(orig_js, good_js)
        self.assertTrue(res_good.is_valid)

    def test_generic_integrity(self):
        orig_js = "function add(a, b) { return a + b; }"
        good_js = "function add(a, b) { return Number(a) + Number(b); }"
        empty_js = ""

        self.assertTrue(CodeValidator.validate_generic_integrity(orig_js, good_js).is_valid)
        self.assertFalse(CodeValidator.validate_generic_integrity(orig_js, empty_js).is_valid)

    def test_model_name_downgrade_rejected(self):
        orig = 'client.messages.create(model="claude-sonnet-4-5", max_tokens=1024)'
        bad_refactored = 'client.messages.create(model="claude-3-5-sonnet-20241022", max_tokens=1024)'
        good_refactored = 'client.messages.create(model="claude-sonnet-4-5", max_tokens=2048)'

        res_bad = CodeValidator.validate_model_name_integrity(orig, bad_refactored)
        self.assertFalse(res_bad.is_valid)
        self.assertIn("downgrade", res_bad.error_message.lower())

        res_good = CodeValidator.validate_model_name_integrity(orig, good_refactored)
        self.assertTrue(res_good.is_valid)

    def test_client_v2_downgrade_rejected(self):
        orig = 'co = cohere.ClientV2(api_key=key)'
        bad_refactored = 'co = cohere.Client(api_key=key)'
        good_refactored = 'co = cohere.ClientV2(api_key=key, timeout=30)'

        res_bad = CodeValidator.validate_model_name_integrity(orig, bad_refactored)
        self.assertFalse(res_bad.is_valid)
        self.assertIn("ClientV2", res_bad.error_message)

        res_good = CodeValidator.validate_model_name_integrity(orig, good_refactored)
        self.assertTrue(res_good.is_valid)

    def test_decorator_definition_order_rejected(self):
        bad_code = """
@app.post("/items")
def create_item():
    return {"status": "ok"}

app = FastAPI(lifespan=lifespan)
"""
        res = CodeValidator.validate_decorator_definition_order(bad_code)
        self.assertFalse(res.is_valid)
        self.assertIn("app", res.error_message)
        self.assertIn("before it is defined", res.error_message)

    def test_decorator_definition_order_valid(self):
        good_code = """
app = FastAPI(lifespan=lifespan)

@app.post("/items")
def create_item():
    return {"status": "ok"}
"""
        res = CodeValidator.validate_decorator_definition_order(good_code)
        self.assertTrue(res.is_valid)

    def test_strip_code_fences_during_validation(self):
        fenced_code = """```python
import os

def hello():
    return "world"
```"""
        orig_code = """import os

def hello():
    return "world"
"""
        res = CodeValidator.validate(orig_code, fenced_code, file_extension=".py")
        self.assertTrue(res.is_valid, f"Expected valid result, got: {res.error_message}")


if __name__ == "__main__":
    unittest.main()

