"""
ApiPatch Autonomous Dependency & Import Detector
Discovers all third-party libraries used in a project (Python, JavaScript, TypeScript)
without any hardcoded rules — enabling the LLM engine to reason about ANY library.
Also provides fast local pre-filtering and repository context generation.
"""

import os
import ast
import json
import re
from typing import List, Set, Dict, Any, Optional
from apipatch.providers.factory import ProviderFactory

# Python standard library module names (excluded from "third-party" list)
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

# Node.js built-in modules (excluded from third-party list for JS/TS projects)
NODE_BUILTIN_MODULES = {
    "fs", "path", "http", "https", "os", "crypto", "stream", "util", "events",
    "child_process", "cluster", "dgram", "dns", "domain", "net", "querystring",
    "readline", "repl", "string_decoder", "timers", "tls", "tty", "url",
    "v8", "vm", "worker_threads", "zlib", "buffer", "assert", "console",
    "module", "process", "inspector", "perf_hooks", "async_hooks", "node:fs",
    "node:path", "node:http", "node:https", "node:os", "node:crypto",
    "node:stream", "node:util", "node:events", "node:child_process", "node:buffer"
}


def _strip_js_comments(code: str) -> str:
    """Removes single-line and multi-line comments from JS/TS code while preserving strings."""
    def replacer(match):
        s = match.group(0)
        if s.startswith('/'):
            return " "
        return s
    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"|`(?:\\.|[^\\`])*`',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, code)


def extract_imports_from_code(content: str) -> Set[str]:
    """
    Extracts top-level module/package names from Python code string.
    """
    imports: Set[str] = set()
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
    except Exception:
        pass
    return imports


def extract_imports_from_js_code(content: str) -> Set[str]:
    """
    Extracts third-party package names from JS/TS code string.
    Supports ESM, CommonJS, dynamic imports, type imports, and re-exports.
    """
    imports: Set[str] = set()
    cleaned = _strip_js_comments(content)

    # 1. ESM: import ... from 'pkg' | import 'pkg' | import type ... from 'pkg'
    esm_patterns = re.findall(
        r"""(?:^|\n|;)\s*import\s+(?:type\s+|typeof\s+)?(?:[^'"]*?from\s+)?['"]([@\w][\w/.-]*)['"]""",
        cleaned
    )
    # 2. Re-exports: export ... from 'pkg'
    export_patterns = re.findall(
        r"""(?:^|\n|;)\s*export\s+(?:[^'"]*?from\s+)?['"]([@\w][\w/.-]*)['"]""",
        cleaned
    )
    # 3. Dynamic imports: import('pkg')
    dyn_import_patterns = re.findall(
        r"""import\s*\(\s*['"]([@\w][\w/.-]*)['"]\s*\)""",
        cleaned
    )
    # 4. CJS: require('pkg')
    cjs_patterns = re.findall(
        r"""require\s*\(\s*['"]([@\w][\w/.-]*)['"]\s*\)""",
        cleaned
    )

    all_raw = esm_patterns + export_patterns + dyn_import_patterns + cjs_patterns
    for raw in all_raw:
        raw = raw.strip()
        if not raw or raw.startswith('.'):
            continue
        if raw.startswith('@'):
            parts = raw.split('/')
            pkg = '/'.join(parts[:2]) if len(parts) >= 2 else raw
        else:
            pkg = raw.split('/')[0]

        if pkg and pkg not in NODE_BUILTIN_MODULES:
            imports.add(pkg)

    return imports


def should_audit_file(
    file_content: str,
    file_path: str,
    detected_libraries: Optional[List[str]] = None
) -> bool:
    """
    Fast local pre-filter (runs in ~0.001s).
    Determines whether a file references any of the detected project libraries.
    If the file is completely clean of third-party references, returns False,
    saving 100% of LLM tokens and API calls.
    """
    if not file_content or not file_content.strip():
        return False

    ext = os.path.splitext(file_path)[1].lower()

    if not detected_libraries:
        # Autonomous in-memory check: if file only imports standard library, skip LLM!
        if ext in {".py", ".pyw"}:
            file_imports = extract_imports_from_code(file_content)
            third_party = file_imports - STANDARD_LIB_MODULES
            return bool(third_party)
        elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            js_imports = extract_imports_from_js_code(file_content)
            return bool(js_imports)
        return True

    normalized_libs = set()
    for lib in detected_libraries:
        lib_clean = lib.strip().lower()
        if lib_clean:
            normalized_libs.add(lib_clean)
            normalized_libs.add(lib_clean.replace('-', '_'))
            normalized_libs.add(lib_clean.replace('_', '-'))
            if '-' in lib_clean:
                normalized_libs.add(lib_clean.split('-')[0])
            if '.' in lib_clean:
                normalized_libs.add(lib_clean.split('.')[0])
            if lib_clean.startswith('@') and '/' in lib_clean:
                scoped_name = lib_clean.split('/')[1]
                normalized_libs.add(scoped_name)

    # 1. Python AST check
    if ext in {".py", ".pyw"}:
        try:
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split('.')[0].lower()
                        if top_pkg in normalized_libs or top_pkg.replace('_', '-') in normalized_libs:
                            return True
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_pkg = node.module.split('.')[0].lower()
                        if top_pkg in normalized_libs or top_pkg.replace('_', '-') in normalized_libs:
                            return True
        except Exception:
            pass

    # 2. JS / TS import extraction check
    elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        js_imports = extract_imports_from_js_code(file_content)
        for imp in js_imports:
            imp_lower = imp.lower()
            if imp_lower in normalized_libs:
                return True
            if imp_lower.startswith('@') and '/' in imp_lower:
                scoped_name = imp_lower.split('/')[1]
                if scoped_name in normalized_libs:
                    return True

    # 3. Fast keyword / token scan for any direct mentions
    lower_content = file_content.lower()
    for lib in normalized_libs:
        if not lib:
            continue
        escaped = re.escape(lib)
        if re.search(r'(?<![a-zA-Z0-9_\-])' + escaped + r'(?![a-zA-Z0-9_\-])', lower_content):
            return True

    return False


def _extract_pyproject_dependencies(target_dir: str) -> Dict[str, str]:
    """Extracts declared package dependencies and versions from pyproject.toml."""
    manifest_deps: Dict[str, str] = {}
    pyproject_path = os.path.join(target_dir, "pyproject.toml")
    if not os.path.exists(pyproject_path):
        return manifest_deps

    try:
        try:
            import tomllib
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            proj_deps = data.get("project", {}).get("dependencies", [])
            for d in proj_deps:
                parts = re.split(r"([><=~;!@\[].*)", d, maxsplit=1)
                pkg = parts[0].strip().lower()
                ver = parts[1].strip() if len(parts) > 1 else "latest"
                if pkg and pkg not in {"apipatch", "setuptools", "wheel", "pytest", "python"}:
                    manifest_deps[pkg] = ver

            opt_deps = data.get("project", {}).get("optional-dependencies", {})
            for group, d_list in opt_deps.items():
                for d in d_list:
                    parts = re.split(r"([><=~;!@\[].*)", d, maxsplit=1)
                    pkg = parts[0].strip().lower()
                    ver = parts[1].strip() if len(parts) > 1 else "latest"
                    if pkg and pkg not in {"apipatch", "setuptools", "wheel", "pytest", "python"}:
                        manifest_deps[pkg] = ver
            return manifest_deps
        except Exception:
            pass

        # Fallback to targeted regex inside dependencies blocks
        with open(pyproject_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        dep_blocks = re.findall(r'(?:dependencies|optional-dependencies)[\s\S]*?\]', content)
        for block in dep_blocks:
            for match in re.findall(r'"([a-zA-Z0-9_\-]+(?:[><=~;].*)?)"', block):
                m = match.strip().lower()
                parts = re.split(r"([><=~;!@].*)", m, maxsplit=1)
                pkg = parts[0].strip()
                ver = parts[1].strip() if len(parts) > 1 else "latest"
                if pkg and pkg not in {"apipatch", "setuptools", "wheel", "pytest", "python"}:
                    manifest_deps[pkg] = ver
    except Exception:
        pass
    return manifest_deps


def build_project_context(target_dir: str, max_file_tree: int = 30) -> str:
    """
    Generates a concise architectural summary of the target project
    (frameworks, declared dependency versions, target runtime & CI/CD matrix constraints, top-level structure)
    to provide high-precision context for LLM migration reasoning.
    """
    target_dir = os.path.abspath(target_dir)
    context_lines: List[str] = []

    # Target Runtime & CI/CD Matrix Awareness
    try:
        from apipatch.runtime_detector import TargetRuntimeDetector
        runtime_ctx = TargetRuntimeDetector.detect_from_directory(target_dir)
        prompt_block = runtime_ctx.to_prompt_context()
        if prompt_block:
            context_lines.append(prompt_block)
    except Exception:
        pass

    frameworks: List[str] = []
    manifest_deps: Dict[str, str] = {}

    # Check requirements.txt
    req_path = os.path.join(target_dir, "requirements.txt")
    if os.path.exists(req_path):
        try:
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        parts = re.split(r"([><=~;!@].*)", line, maxsplit=1)
                        pkg = parts[0].strip().lower()
                        ver = parts[1].strip() if len(parts) > 1 else "latest"
                        manifest_deps[pkg] = ver
        except Exception:
            pass

    # Check pyproject.toml
    manifest_deps.update(_extract_pyproject_dependencies(target_dir))

    # Check package.json
    pkg_json = os.path.join(target_dir, "package.json")
    if os.path.exists(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            for k in ("dependencies", "devDependencies"):
                if k in data and isinstance(data[k], dict):
                    for pkg, ver in data[k].items():
                        manifest_deps[pkg.lower()] = str(ver)
        except Exception:
            pass

    # Infer frameworks
    dep_keys = set(manifest_deps.keys())
    if "fastapi" in dep_keys:
        frameworks.append("FastAPI")
    if "django" in dep_keys:
        frameworks.append("Django")
    if "flask" in dep_keys:
        frameworks.append("Flask")
    if "next" in dep_keys or os.path.exists(os.path.join(target_dir, "next.config.js")):
        frameworks.append("Next.js")
    if "react" in dep_keys:
        frameworks.append("React")
    if "express" in dep_keys:
        frameworks.append("Express.js")
    if "pydantic" in dep_keys:
        frameworks.append("Pydantic")
    if "langchain" in dep_keys or "langchain-core" in dep_keys:
        frameworks.append("LangChain")
    if "openai" in dep_keys:
        frameworks.append("OpenAI SDK")
    if "stripe" in dep_keys:
        frameworks.append("Stripe SDK")

    if frameworks:
        context_lines.append(f"Detected Frameworks/Stack: {', '.join(frameworks)}")

    if manifest_deps:
        sample_deps = [f"{k}{' ' + v if v != 'latest' else ''}" for k, v in list(manifest_deps.items())[:15]]
        context_lines.append(f"Key Dependencies: {', '.join(sample_deps)}")

    # Summarize top project structure
    ignore_dirs = {
        ".git", "node_modules", "venv", ".venv", "__pycache__",
        ".gemini", "dist", "build", ".next", ".nuxt", "out", "coverage"
    }
    top_files: List[str] = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), target_dir)
            ext = os.path.splitext(f)[1].lower()
            if ext in {".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".toml"}:
                top_files.append(rel.replace("\\", "/"))
            if len(top_files) >= max_file_tree:
                break
        if len(top_files) >= max_file_tree:
            break

    if top_files:
        context_lines.append("Project Structure Preview:")
        for tf in top_files[:10]:
            context_lines.append(f"  - {tf}")
        if len(top_files) > 10:
            context_lines.append(f"  ... (+{len(top_files) - 10} more files)")

    return "\n".join(context_lines)


class AutoDeprecationDetector:
    def __init__(
        self,
        target_dir: str = ".",
        provider_name: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        self.target_dir = os.path.abspath(target_dir)
        self.provider = ProviderFactory.get_provider(
            provider_name=provider_name, api_key=api_key
        )

    # ─── Python Import Extraction ─────────────────────────────────────────────

    def extract_imports_from_code(self, content: str) -> Set[str]:
        """
        Extracts all third-party imported module names directly from a Python source code string.
        Uses Python AST with automatic regex fallback.
        """
        imports: Set[str] = set()
        if not content:
            return imports
        try:
            tree = ast.parse(content.lstrip('\ufeff'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split('.')[0]
                        if top_pkg not in STANDARD_LIB_MODULES:
                            imports.add(top_pkg)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top_pkg = node.module.split('.')[0]
                        if top_pkg not in STANDARD_LIB_MODULES:
                            imports.add(top_pkg)
        except Exception:
            for match in re.finditer(r'(?:^|\n)\s*(?:from|import)\s+([a-zA-Z0-9_]+)', content):
                pkg = match.group(1).split('.')[0]
                if pkg and pkg not in STANDARD_LIB_MODULES:
                    imports.add(pkg)
        return imports

    def extract_imports_from_file(self, file_path: str) -> Set[str]:
        """
        Extracts all third-party imported module names from a .py or .pyw source file.
        Uses Python AST with automatic regex fallback for syntax/encoding edge cases.
        """
        if not file_path.endswith((".py", ".pyw")):
            return set()
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                content = f.read()
            return self.extract_imports_from_code(content)
        except Exception:
            return set()

    # ─── JS/TS Import Extraction ──────────────────────────────────────────────

    def extract_imports_from_js_file(self, file_path: str) -> Set[str]:
        """
        Uses regex and comment stripping to extract third-party package names
        from JS / TS / JSX / TSX / MJS / CJS source files.
        """
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            return set()
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return extract_imports_from_js_code(content)
        except Exception:
            return set()

    # ─── Manifest-based Dependency Discovery ─────────────────────────────────

    def _parse_requirements_txt(self) -> Set[str]:
        deps: Set[str] = set()
        req_path = os.path.join(self.target_dir, "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("-"):
                        pkg = re.split(r"[><=~;!@\[]", line)[0].strip().lower()
                        if pkg:
                            deps.add(pkg)
        return deps

    def _parse_package_json(self) -> Set[str]:
        deps: Set[str] = set()
        pkg_json = os.path.join(self.target_dir, "package.json")
        if os.path.exists(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    if key in data and isinstance(data[key], dict):
                        deps.update(p.lower() for p in data[key].keys())
            except Exception:
                pass
        return deps

    def _parse_pyproject_toml(self) -> Set[str]:
        deps = set(_extract_pyproject_dependencies(self.target_dir).keys())
        return deps

    # ─── Main Detection API ───────────────────────────────────────────────────

    def detect_dependencies(self) -> List[str]:
        """
        Discovers all third-party packages from:
        1. requirements.txt
        2. package.json
        3. pyproject.toml
        4. Recursive AST inspection of Python source files
        5. Regex inspection of JS/TS source files
        """
        dependencies: Set[str] = set()

        dependencies.update(self._parse_requirements_txt())
        dependencies.update(self._parse_package_json())
        dependencies.update(self._parse_pyproject_toml())

        ignore_dirs = {
            ".git", "node_modules", "venv", ".venv", "__pycache__",
            ".gemini", "dist", "build", ".next", ".nuxt", "out", "coverage"
        }

        for root, dirs, files in os.walk(self.target_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for file in files:
                full_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                if ext in {".py", ".pyw"}:
                    dependencies.update(self.extract_imports_from_file(full_path))
                elif ext in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
                    dependencies.update(self.extract_imports_from_js_file(full_path))

        return sorted(dependencies)

    def should_audit_file(self, file_content: str, file_path: str, detected_libraries: Optional[List[str]] = None) -> bool:
        """Instance method shortcut for should_audit_file."""
        return should_audit_file(file_content, file_path, detected_libraries)

    def get_project_context(self) -> str:
        """Returns the project architectural and manifest context string."""
        return build_project_context(self.target_dir)

    def run_autonomous_discovery(self) -> Dict[str, Any]:
        """Runs end-to-end autonomous dependency discovery and prints a summary."""
        deps = self.detect_dependencies()
        print(f"\n[ApiPatch] Detected {len(deps)} third-party package(s) in '{self.target_dir}':")
        for dep in deps:
            print(f"  - {dep}")
        print(
            "\nAll detected packages will be passed to the AI engine "
            "for dynamic deprecation analysis when you run `apipatch scan` or `apipatch fix`.\n"
        )
        return {
            "target_directory": self.target_dir,
            "detected_packages": deps,
            "project_context": self.get_project_context()
        }
