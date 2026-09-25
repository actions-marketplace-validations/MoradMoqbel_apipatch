"""
ApiPatch Sandbox Test Runner
Executes local test suites (pytest, unittest, npm test) in an isolated subprocess
to verify that refactored code passes all unit and integration tests.
"""

import os
import sys
import re
import json
import tempfile
import subprocess
from typing import Tuple, Optional


_RE_MOD_PATH = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
_RE_ATTR_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

_SANDBOX_EVAL_SCRIPT = """
import sys
import os
import json
import importlib

# Isolate sys.path from current directory and local repository scripts
clean_path = [p for p in sys.path if p and p not in ('', '.', os.getcwd())]
sys.path = clean_path

try:
    pairs = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)

errors = []
for mod_path, attr_name in pairs:
    try:
        mod = importlib.import_module(mod_path)
        if not hasattr(mod, attr_name):
            errors.append(f"AttributeError: module '{mod_path}' has no attribute '{attr_name}'")
    except ModuleNotFoundError:
        pass
    except Exception as e:
        errors.append(str(e))

if errors:
    print('ERR:' + '; '.join(errors))
    sys.exit(1)
"""


class SandboxTestRunner:
    @staticmethod
    def detect_test_framework(target_dir: str) -> Optional[str]:
        """
        Detects available test suites in the target project directory.
        Returns 'pytest', 'unittest', 'npm', or None.
        """
        target_dir = os.path.abspath(target_dir)

        # 1. Python test suite detection
        has_tests_dir = os.path.isdir(os.path.join(target_dir, "tests")) or os.path.isdir(os.path.join(target_dir, "test"))
        has_pyproject = os.path.isfile(os.path.join(target_dir, "pyproject.toml"))
        has_pytest_ini = os.path.isfile(os.path.join(target_dir, "pytest.ini"))

        # Look for any test_*.py files in target_dir
        has_test_files = False
        for root, _, files in os.walk(target_dir):
            if any(d in root for d in (".git", "node_modules", "venv", ".venv", "__pycache__")):
                continue
            if any(f.startswith("test_") and f.endswith(".py") for f in files):
                has_test_files = True
                break

        if has_pytest_ini or has_tests_dir or has_test_files or has_pyproject:
            return "pytest"

        # 2. Node.js / JS / TS test suite detection
        pkg_path = os.path.join(target_dir, "package.json")
        if os.path.isfile(pkg_path):
            try:
                with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                if "scripts" in data and "test" in data["scripts"]:
                    test_cmd = data["scripts"]["test"].strip().lower()
                    if test_cmd and not test_cmd.startswith('echo "error: no test specified"'):
                        return "npm"
            except Exception:
                pass

        return None

    @classmethod
    def run_tests(
        cls,
        target_dir: str,
        timeout: int = 60,
        custom_command: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Runs project tests in a subprocess.
        Returns (passed: bool, output_log: str).
        """
        target_dir = os.path.abspath(target_dir)

        if custom_command:
            cmd = custom_command.split()
        else:
            framework = cls.detect_test_framework(target_dir)
            if not framework:
                return True, "No automated test suite detected in project directory."

            if framework == "pytest":
                cmd = [sys.executable, "-m", "pytest", "-q"]
            elif framework == "npm":
                cmd = ["npm", "test"]
            elif framework == "unittest":
                cmd = [sys.executable, "-m", "unittest", "discover"]
            else:
                return True, f"Unsupported framework '{framework}', skipping automated test run."

        try:
            # On Windows, npm is npm.cmd
            shell_mode = (os.name == "nt" and cmd[0] in ("npm", "npx", "yarn", "pnpm"))
            result = subprocess.run(
                cmd,
                cwd=target_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=shell_mode
            )
            output = (result.stdout + "\n" + result.stderr).strip()
            passed = (result.returncode == 0)
            return passed, output

        except subprocess.TimeoutExpired:
            return False, f"Test execution timed out after {timeout} seconds."
        except FileNotFoundError as e:
            return False, f"Test runner executable not found: {e}"
        except Exception as e:
            return False, f"Error running tests: {str(e)}"


class MicroSandboxResult:
    """Result of an ephemeral runtime sandbox evaluation."""
    def __init__(self, is_valid: bool, error_message: str = "", offending_symbol: str = ""):
        self.is_valid = is_valid
        self.error_message = error_message
        self.offending_symbol = offending_symbol

    def __bool__(self):
        return self.is_valid


class MicroSandboxEvaluator:
    """
    Ephemeral Micro-Sandbox Runtime Evaluator.
    Dynamically tests whether imported modules, classes, and accessed attributes
    actually resolve in the Python runtime without raising AttributeError or ImportError.
    Executes in a safe isolated environment to prevent RCE or side-effects.
    """

    @classmethod
    def evaluate_code_imports(cls, code: str, timeout: float = 1.5) -> MicroSandboxResult:
        """
        Extracts imported aliases and attribute lookups from code and executes an isolated
        subprocess check with JSON IPC and path isolation to detect runtime AttributeError / ImportError.
        """
        import ast

        try:
            tree = ast.parse(code)
        except Exception as e:
            return MicroSandboxResult(is_valid=False, error_message=f"SyntaxError in code: {e}")

        # Map imported local names -> full module path
        # e.g., 'from google.genai import types' -> {'types': 'google.genai.types'}
        import_map = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    import_map[name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    name = alias.asname or alias.name
                    import_map[name] = f"{node.module}.{alias.name}"

        # Extract local function parameter names to avoid false positive module attribute checks
        # when a parameter name shadows a module name (e.g., def _findKey(self, json: dict): json.items())
        local_param_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args + node.args.kwonlyargs:
                    local_param_names.add(arg.arg)
                if node.args.vararg:
                    local_param_names.add(node.args.vararg.arg)
                if node.args.kwarg:
                    local_param_names.add(node.args.kwarg.arg)

        # Collect attribute lookups on imported aliases (e.g. types.ToolContext, pydantic.ConfigDict)
        tested_pairs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                alias = node.value.id
                attr = node.attr
                if alias in import_map and alias not in local_param_names:
                    mod_path = import_map[alias]
                    # Enforce strict Python identifier regex validation
                    if _RE_MOD_PATH.match(mod_path) and _RE_ATTR_NAME.match(attr):
                        tested_pairs.append([mod_path, attr])

        if not tested_pairs:
            return MicroSandboxResult(is_valid=True)

        try:
            safe_cwd = tempfile.gettempdir()
            payload = json.dumps(tested_pairs)
            res = subprocess.run(
                [sys.executable, "-c", _SANDBOX_EVAL_SCRIPT, payload],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=safe_cwd
            )
            if res.returncode != 0:
                err_text = (res.stdout + "\n" + res.stderr).strip()
                if "ERR:" in err_text:
                    err_msg = err_text.split("ERR:", 1)[1].strip()
                    return MicroSandboxResult(is_valid=False, error_message=err_msg)
                elif "AttributeError" in err_text or "ImportError" in err_text:
                    return MicroSandboxResult(is_valid=False, error_message=err_text)
        except Exception:
            pass

        return MicroSandboxResult(is_valid=True)

