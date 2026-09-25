"""
Unit tests for Anthropic Claude Modern Messages API & Tool-Use Migration
"""

import unittest
import ast
from apipatch.knowledge import get_relevant_knowledge
from apipatch.validator import CodeValidator


class TestAnthropicMigration(unittest.TestCase):
    def test_anthropic_2026_guidance_includes_messages_and_tools(self):
        guidance = get_relevant_knowledge(
            detected_libraries=["anthropic"],
            file_content="client.completion(prompt='Human: Hello AI: ')"
        )
        self.assertIn("Anthropic Claude 2026", guidance)
        self.assertIn("client.messages.create", guidance)
        self.assertIn("claude-3-5-sonnet", guidance)
        self.assertIn("tools", guidance)
        self.assertIn("input_schema", guidance)

    def test_anthropic_modern_tool_calling_ast_validity(self):
        modern_code = '''\
from anthropic import Anthropic

client = Anthropic()

TOOLS = [{
    "name": "fetch_weather",
    "description": "Fetches current temperature and weather conditions",
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"}
        },
        "required": ["city"]
    }
}]

def ask_claude_with_tools(user_query: str) -> str:
    """Executes Claude 3.5 Sonnet with structured tool calling."""
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        tools=TOOLS,
        messages=[{"role": "user", "content": user_query}]
    )
    for block in response.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
'''
        # Must be valid Python AST
        tree = ast.parse(modern_code)
        self.assertIsNotNone(tree)

        # Must pass ApiPatch safety validation
        result = CodeValidator.validate_python_syntax(modern_code)
        self.assertTrue(result.is_valid, f"Validation errors: {result.error_message}")

    def test_anthropic_claude_aliases(self):
        for alias in ["anthropic", "@anthropic-ai/sdk", "claude"]:
            guidance = get_relevant_knowledge(detected_libraries=[alias])
            self.assertIn("Anthropic Claude", guidance)


if __name__ == "__main__":
    unittest.main()
