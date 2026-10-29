import pytest
from apipatch.knowledge import MIGRATION_KNOWLEDGE_BASE

def test_sqlalchemy_knowledge_registered():
    assert "sqlalchemy" in MIGRATION_KNOWLEDGE_BASE
    entry = MIGRATION_KNOWLEDGE_BASE["sqlalchemy"]
    assert "alembic" in entry["aliases"]
    assert "DeclarativeBase" in entry["guidance"]
    assert "select" in entry["guidance"]
    assert "scalar_one" in entry["guidance"]
