"""
Unit tests for LangChain v0.3+ Enterprise Migration & AST Safety Rules
"""

import unittest
import ast
from apipatch.knowledge import get_relevant_knowledge, MIGRATION_KNOWLEDGE_BASE
from apipatch.validator import CodeValidator


class TestLangChainMigration(unittest.TestCase):
    def test_langchain_v03_guidance_includes_lcel_and_partner_pkgs(self):
        guidance = get_relevant_knowledge(
            detected_libraries=["langchain"],
            file_content="from langchain.chains import LLMChain\nfrom langchain.chat_models import ChatOpenAI"
        )
        self.assertIn("LangChain v0.3+", guidance)
        self.assertIn("langchain_openai", guidance)
        self.assertIn("langchain_anthropic", guidance)
        self.assertIn("prompt | llm", guidance)
        self.assertIn("create_retrieval_chain", guidance)
        self.assertIn("invoke", guidance)

    def test_langchain_modern_code_ast_validity(self):
        modern_code = '''\
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

prompt = ChatPromptTemplate.from_template("Summarize: {topic}")
llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
chain = prompt | llm | StrOutputParser()

def run_pipeline(topic: str) -> str:
    """Executes the modern LCEL chain."""
    return chain.invoke({"topic": topic})
'''
        # Must be valid Python AST
        tree = ast.parse(modern_code)
        self.assertIsNotNone(tree)

        # Must pass ApiPatch safety validation
        result = CodeValidator.validate_python_syntax(modern_code)
        self.assertTrue(result.is_valid, f"Validation errors: {result.error_message}")

    def test_langchain_partner_aliases_recognized(self):
        for alias in ["langchain-core", "langchain-community", "langchain-openai", "langgraph"]:
            guidance = get_relevant_knowledge(detected_libraries=[alias])
            self.assertIn("LangChain v0.3+", guidance)


if __name__ == "__main__":
    unittest.main()
