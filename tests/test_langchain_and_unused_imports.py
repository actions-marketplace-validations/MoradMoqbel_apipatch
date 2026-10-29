import pytest
from apipatch.validator import CodeValidator

def test_invalid_langchain_core_chat_models_import():
    code = """
from langchain_core.chat_models import BaseChatModel

class CustomModel(BaseChatModel):
    pass
"""
    res = CodeValidator.validate_python_syntax(code)
    assert not res.is_valid
    assert "langchain_core.chat_models" in res.error_message
    assert "langchain_core.language_models.chat_models" in res.error_message

def test_unused_import_detection():
    orig = """
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import AIMessage
"""
    ref_with_unused = """
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolCall

def process():
    return [AIMessage(content="hi"), HumanMessage(content="user"), SystemMessage(content="sys")]
"""
    res = CodeValidator.validate_unused_imports(orig, ref_with_unused)
    assert not res.is_valid
    assert "ToolCall" in res.error_message
    assert "Unused import" in res.error_message

def test_clean_import_passes():
    orig = """
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import AIMessage
"""
    ref_clean = """
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

def process():
    return [AIMessage(content="hi"), HumanMessage(content="user"), SystemMessage(content="sys")]
"""
    res = CodeValidator.validate_unused_imports(orig, ref_clean)
    assert res.is_valid
