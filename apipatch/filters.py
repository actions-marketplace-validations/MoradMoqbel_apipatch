"""
ApiPatch Path & File Filters
Provides dynamic, zero-overhead ignore filtering for documentation, test files, and non-production assets.
"""

import os
import re
from typing import List, Set, Tuple, Optional

# Standard documentation directory names across ecosystems
DOCS_DIR_NAMES: Set[str] = {
    "docs", "doc", "documentation", "site", "website", "gh-pages", "guide", "guides", "manual"
}

# Standard test directory names across ecosystems
TESTS_DIR_NAMES: Set[str] = {
    "tests", "test", "testing", "__tests__", "__test__", "spec", "specs", "fixtures", "mocks", "e2e"
}

# Standard test file patterns
TEST_FILE_PATTERNS: Tuple[str, ...] = (
    "test_", "_test.py", "_tests.py", "conftest.py",
    ".test.", ".spec."
)

# Standard non-production sample, tutorial, and benchmark directories
NON_PROD_DIR_NAMES: Set[str] = {
    "examples", "example", "samples", "sample", "benchmarks", "benchmark",
    "tutorials", "tutorial", "demo", "demos", "notebooks", "notebook", "playground"
}

DOC_FILE_EXTENSIONS: Set[str] = {
    ".md", ".mdx", ".rst", ".txt", ".adoc", ".pdf"
}


def is_doc_path(path: str) -> bool:
    """
    Returns True if the path belongs to documentation (e.g. docs/, website/, etc.).
    """
    if not path:
        return False
    norm = path.replace("\\", "/").strip("/").lower()
    parts = norm.split("/")

    # Check directory segments
    for seg in parts[:-1]:
        if seg in DOCS_DIR_NAMES:
            return True

    # If the path itself is a docs directory or filename
    if len(parts) == 1 and parts[0] in DOCS_DIR_NAMES:
        return True

    return False


def is_test_path(path: str) -> bool:
    """
    Returns True if the path belongs to tests (e.g. tests/, __tests__/, or test_*.py, *.test.ts).
    """
    if not path:
        return False
    norm = path.replace("\\", "/").strip("/").lower()
    parts = norm.split("/")

    # Check directory segments
    for seg in parts[:-1]:
        if seg in TESTS_DIR_NAMES:
            return True

    filename = parts[-1]
    # Check test filename patterns
    if filename.startswith("test_"):
        return True
    if filename.endswith(("_test.py", "_tests.py", "conftest.py")):
        return True
    if ".test." in filename or ".spec." in filename:
        return True

    return False


def is_non_prod_path(path: str) -> bool:
    """
    Returns True if the path belongs to non-production samples, tutorials, or benchmarks
    (e.g. examples/, samples/, benchmarks/, tutorials/, demo/, notebooks/).
    """
    if not path:
        return False
    norm = path.replace("\\", "/").strip("/").lower()
    parts = norm.split("/")

    for seg in parts[:-1]:
        if seg in NON_PROD_DIR_NAMES:
            return True

    if len(parts) == 1 and parts[0] in NON_PROD_DIR_NAMES:
        return True

    if parts[-1].endswith(".ipynb"):
        return True

    return False


def should_ignore_path(
    path: str,
    ignore_docs: bool = True,
    ignore_tests: bool = True,
    ignore_non_prod: bool = True,
    custom_ignore_patterns: Optional[List[str]] = None
) -> bool:
    """
    Dynamically checks whether a path should be ignored during audit or scan.
    """
    if not path:
        return False

    if ignore_docs and is_doc_path(path):
        return True

    if ignore_tests and is_test_path(path):
        return True

    if ignore_non_prod and is_non_prod_path(path):
        return True

    if custom_ignore_patterns:
        norm = path.replace("\\", "/").lower()
        for pat in custom_ignore_patterns:
            if pat.lower() in norm:
                return True

    return False

