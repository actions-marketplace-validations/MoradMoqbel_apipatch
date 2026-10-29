import pytest
from apipatch.runtime_inspector import RuntimeInspector

def test_verify_nonexistent_submodule_with_canonical_suggestion():
    # Test that langchain_core.chat_models is detected as nonexistent,
    # and that BaseChatModel is found in langchain_core.language_models.chat_models!
    valid, err = RuntimeInspector.verify_import_statement("langchain_core.chat_models", "BaseChatModel")
    print(f"Result for langchain_core.chat_models: valid={valid}, err={err}")
    assert not valid
    assert "ModuleNotFoundError" in err
    assert "BaseChatModel" in err
    assert "langchain_core.language_models.chat_models" in err

def test_verify_canonical_import_passes():
    valid, err = RuntimeInspector.verify_import_statement("langchain_core.language_models.chat_models", "BaseChatModel")
    assert valid
    assert err is None

def test_verify_standard_library_always_passes():
    valid, err = RuntimeInspector.verify_import_statement("urllib.parse", "quote")
    assert valid
    assert err is None

def test_verify_callable_signature_valid():
    def my_func(a: int, b: str = "hello", *args, key: bool = False):
        pass

    valid, err = RuntimeInspector.verify_callable_signature(my_func, {"a": 1, "key": True})
    assert valid
    assert err is None

def test_verify_callable_signature_unexpected_keyword():
    def my_func(a: int, b: str = "hello"):
        pass

    valid, err = RuntimeInspector.verify_callable_signature(my_func, {"a": 1, "invalid_arg": 123})
    assert not valid
    assert "unexpected keyword argument 'invalid_arg'" in err

def test_verify_code_imports():
    bad_code = """
import os
from langchain_core.chat_models import BaseChatModel
from urllib.parse import quote
"""
    errors = RuntimeInspector.verify_code_imports(bad_code)
    print("Errors from bad_code:", errors)
    assert len(errors) == 1
    assert "langchain_core.language_models.chat_models" in errors[0]
