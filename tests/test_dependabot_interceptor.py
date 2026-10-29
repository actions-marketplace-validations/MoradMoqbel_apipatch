import unittest
from apipatch.dependabot_interceptor import DependabotInterceptor, BREAKING_DELTA_CATALOG

class TestDependabotInterceptor(unittest.TestCase):

    def test_parse_pr_bump_title(self):
        title = "chore(deps): Bump langchain from 0.2.14 to 0.3.1"
        bumps = DependabotInterceptor.parse_pr_bump(title)
        self.assertEqual(len(bumps), 1)
        self.assertEqual(bumps[0]["package"], "langchain")
        self.assertEqual(bumps[0]["old_version"], "0.2.14")
        self.assertEqual(bumps[0]["new_version"], "0.3.1")

    def test_parse_pr_bump_table(self):
        body = """Bumps the python-deps group with 2 updates:

| Package | From | To |
| --- | --- | --- |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | `0.25.0` | `0.45.0` |
| [pydantic](https://github.com/pydantic/pydantic) | `1.10.8` | `2.8.2` |
"""
        bumps = DependabotInterceptor.parse_pr_bump("Bump deps group", body)
        self.assertEqual(len(bumps), 2)
        self.assertEqual(bumps[0]["package"], "anthropic")
        self.assertEqual(bumps[1]["package"], "pydantic")

    def test_breaking_delta_catalog_rules(self):
        # Test LangChain breaking rules
        code = """
from langchain.chat_models import ChatOpenAI

def run_agent(query):
    chain = LLMChain(llm=ChatOpenAI(), prompt=prompt)
    return chain.run(query)
"""
        interceptor = DependabotInterceptor(github_token="fake_token")
        rules = BREAKING_DELTA_CATALOG["langchain"]["breaking_rules"]
        
        matches = []
        import re
        for r in rules:
            if re.search(r["pattern"], code):
                matches.append(r["id"])
                
        self.assertIn("langchain_partner_imports", matches)
        self.assertIn("langchain_run_deprecated", matches)

    def test_anthropic_breaking_rules(self):
        code = """
import anthropic
client = anthropic.Anthropic()
res = client.completion(prompt="Hello", model="claude-2")
"""
        rules = BREAKING_DELTA_CATALOG["anthropic"]["breaking_rules"]
        import re
        matches = [r["id"] for r in rules if re.search(r["pattern"], code)]
        self.assertIn("anthropic_completion_removed", matches)

    def test_pydantic_base_settings_rule(self):
        code = """
from pydantic import BaseModel, BaseSettings

class Settings(BaseSettings):
    api_key: str
"""
        rules = BREAKING_DELTA_CATALOG["pydantic"]["breaking_rules"]
        import re
        matches = [r["id"] for r in rules if re.search(r["pattern"], code)]
        self.assertIn("pydantic_base_settings_moved", matches)

if __name__ == "__main__":
    unittest.main()
