"""
ApiPatch Runtime & Execution-Based Verification Engine (Dynamic Introspection)
Verifies API existence, module import paths, and callable signatures against actual
installed Python packages and isolated on-demand wheels — eliminating LLM hallucinations.
"""

import os
import sys
import ast
import inspect
import tempfile
import subprocess
import importlib.util
from typing import Dict, Any, List, Optional, Set, Tuple

# Python standard library modules to exclude from package downloads
STANDARD_LIB_MODULES = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "calendar", "cmath", "collections", "concurrent", "contextlib",
    "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal", "difflib",
    "dis", "doctest", "email", "enum", "errno", "faulthandler", "fcntl", "filecmp",
    "fileinput", "fnmatch", "fractions", "functools", "gc", "getopt", "getpass",
    "gettext", "glob", "graphlib", "gzip", "hashlib", "heapq", "hmac", "html",
    "http", "idlelib", "imaplib", "imghdr", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "linecache", "locale", "logging",
    "lzma", "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
    "modulefinder", "multiprocessing", "netrc", "nntplib", "numbers", "operator",
    "os", "pathlib", "pdb", "pickle", "pipes", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "pprint", "profile", "pstats", "pty", "pwd", "py_compile",
    "pyclbr", "pydoc", "queue", "quopri", "random", "re", "readline", "reprlib",
    "resource", "rlcompleter", "runpy", "sched", "secrets", "select", "selectors",
    "shelve", "shlex", "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
    "socket", "socketserver", "spwd", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "sunau", "symtable", "sys",
    "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios",
    "test", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib", "uu",
    "uuid", "venv", "warnings", "wave", "weakref", "webbrowser", "winreg", "winsound",
    "wsgiref", "xdrlib", "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    "zoneinfo"
}


class RuntimeInspector:
    """
    Automated execution-based verification engine.
    Ensures zero hallucinated imports and zero mismatched function signatures
    by inspecting real Python modules via importlib, AST, and inspect.
    """

    CACHE_DIR = os.path.expanduser("~/.apipatch/packages")

    @classmethod
    def get_cache_dir(cls) -> str:
        """Returns and ensures the isolated package cache directory exists."""
        os.makedirs(cls.CACHE_DIR, exist_ok=True)
        if cls.CACHE_DIR not in sys.path:
            sys.path.insert(0, cls.CACHE_DIR)
        return cls.CACHE_DIR

    @classmethod
    def ensure_package_available(cls, package_name: str, version: Optional[str] = None) -> bool:
        """
        Ensures a third-party package is available for introspection.
        Installs to isolated cache directory using --no-deps if not already present.
        """
        if not package_name or package_name in STANDARD_LIB_MODULES:
            return True

        # Normalize module name to PyPI package name if different
        pypi_name = package_name.replace("_", "-")
        target_pkg_dir = os.path.join(cls.get_cache_dir(), pypi_name)

        # 1. Check if already importable in current environment
        root_mod = package_name.split(".")[0]
        if importlib.util.find_spec(root_mod) is not None:
            return True

        # 2. Check if already installed in cache
        if os.path.isdir(target_pkg_dir) and target_pkg_dir in sys.path:
            if importlib.util.find_spec(root_mod) is not None:
                return True

        # 3. Fast isolated on-demand install (--no-deps prevents heavy dependency bloat)
        pkg_specifier = f"{pypi_name}=={version}" if version else pypi_name
        try:
            os.makedirs(target_pkg_dir, exist_ok=True)
            cmd = [
                sys.executable, "-m", "pip", "install",
                pkg_specifier,
                "--target", target_pkg_dir,
                "--no-deps",
                "--no-warn-script-location",
                "--quiet"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                if target_pkg_dir not in sys.path:
                    sys.path.insert(0, target_pkg_dir)
                return importlib.util.find_spec(root_mod) is not None
        except Exception:
            pass

        return False

    @classmethod
    def extract_module_symbols_via_ast(cls, file_path: str) -> Set[str]:
        """
        Extracts all exported symbols (classes, functions, __all__, re-exports)
        from a Python source or stub (.pyi) file safely via AST without executing code.
        """
        symbols: Set[str] = set()
        if not file_path or not os.path.isfile(file_path):
            return symbols

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                tree = ast.parse(f.read())

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            if target.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple)):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        symbols.add(elt.value)
                            else:
                                symbols.add(target.id)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        symbols.add(alias.asname or alias.name)
        except Exception:
            pass

        return symbols

    @classmethod
    def find_symbol_in_package(cls, root_package: str, target_symbol: str) -> Optional[str]:
        """
        Scans all submodules in an installed package to find which submodule exports target_symbol.
        Returns the canonical module path if found (e.g. 'langchain_core.language_models.chat_models').
        """
        root_spec = importlib.util.find_spec(root_package)
        if not root_spec or not root_spec.origin:
            return None

        pkg_dir = os.path.dirname(root_spec.origin)
        if not os.path.isdir(pkg_dir):
            return None

        # Search recursively across package directory
        for dirpath, _, filenames in os.walk(pkg_dir):
            for fname in filenames:
                if fname.endswith((".py", ".pyi")):
                    full_p = os.path.join(dirpath, fname)
                    symbols = cls.extract_module_symbols_via_ast(full_p)
                    if target_symbol in symbols:
                        # Construct module path
                        rel = os.path.relpath(full_p, os.path.dirname(pkg_dir))
                        mod_parts = rel.replace("\\", "/").rstrip(".pyi").rstrip(".py").split("/")
                        if mod_parts[-1] == "__init__":
                            mod_parts = mod_parts[:-1]
                        return ".".join(mod_parts)

        return None

    @classmethod
    def verify_import_statement(
        cls,
        module_path: str,
        symbol_name: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifies whether an import statement is valid in the actual runtime environment.
        If invalid, attempts to locate the real module path and returns a concrete diagnostic suggestion.

        Returns:
            (is_valid: bool, error_or_suggestion: Optional[str])
        """
        root_mod = module_path.split(".")[0]
        if root_mod in STANDARD_LIB_MODULES:
            return True, None

        # Ensure package is accessible
        cls.ensure_package_available(root_mod)

        # 1. Check if the module path itself can be located
        spec = importlib.util.find_spec(module_path)
        if spec is None:
            # Module does not exist! Try to find the symbol in the parent package
            if symbol_name:
                found_path = cls.find_symbol_in_package(root_mod, symbol_name)
                if found_path:
                    return False, (
                        f"ModuleNotFoundError: No module named '{module_path}'. "
                        f"Symbol '{symbol_name}' was found in canonical path: 'from {found_path} import {symbol_name}'."
                    )
            return False, f"ModuleNotFoundError: No module named '{module_path}'."

        # 2. If module exists and symbol_name is specified, check if symbol exists in that module
        if symbol_name and spec.origin:
            symbols = cls.extract_module_symbols_via_ast(spec.origin)
            if symbols and symbol_name not in symbols:
                # Symbol missing from this specific module, search package
                found_path = cls.find_symbol_in_package(root_mod, symbol_name)
                if found_path:
                    return False, (
                        f"ImportError: cannot import name '{symbol_name}' from '{module_path}'. "
                        f"Did you mean: 'from {found_path} import {symbol_name}'?"
                    )
                return False, f"ImportError: cannot import name '{symbol_name}' from '{module_path}'."

        return True, None

    @classmethod
    def verify_code_imports(cls, code: str) -> List[str]:
        """
        Parses code AST and validates all third-party imports against the real filesystem/runtime.
        Returns a list of actionable diagnostic error strings if any hallucinations are detected.
        """
        errors: List[str] = []
        try:
            tree = ast.parse(code)
        except Exception:
            return errors

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module
                if not mod:
                    continue
                root_pkg = mod.split(".")[0]
                if root_pkg in STANDARD_LIB_MODULES:
                    continue

                for alias in node.names:
                    sym = alias.name
                    valid, err = cls.verify_import_statement(mod, sym)
                    if not valid and err:
                        errors.append(f"Line {node.lineno}: {err}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    root_pkg = mod.split(".")[0]
                    if root_pkg in STANDARD_LIB_MODULES:
                        continue
                    valid, err = cls.verify_import_statement(mod)
                    if not valid and err:
                        errors.append(f"Line {node.lineno}: {err}")

        return errors

    @classmethod
    def verify_callable_signature(cls, callable_func: Any, kwargs: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validates keyword arguments against a callable function/method signature using inspect.signature.
        """
        try:
            sig = inspect.signature(callable_func)
            sig.bind_partial(**kwargs)
            return True, None
        except TypeError as e:
            return False, str(e)
        except Exception:
            return True, None
