"""
ApiPatch Code Validator and Safety Guard
Ensures 100% syntactical correctness and structural integrity of refactored code
across Python, JavaScript, TypeScript, and other supported languages.
"""

import ast
import re
from typing import Tuple, List, Set, Optional


class ValidationResult:
    def __init__(self, is_valid: bool, error_message: Optional[str] = None, error_line: Optional[int] = None):
        self.is_valid = is_valid
        self.error_message = error_message
        self.error_line = error_line

    def __bool__(self) -> bool:
        return self.is_valid

    def __repr__(self) -> str:
        if self.is_valid:
            return "<ValidationResult: Valid>"
        line_info = f"Line {self.error_line}: " if self.error_line else ""
        return f"<ValidationResult: Invalid ({line_info}{self.error_message})>"


class CodeValidator:
    KNOWN_INVALID_IMPORT_NAMES = {
        "python_dotenv": "dotenv (e.g. 'from dotenv import load_dotenv')",
        "pyyaml": "yaml (e.g. 'import yaml')",
        "beautifulsoup4": "bs4 (e.g. 'from bs4 import BeautifulSoup')",
        "pillow": "PIL (e.g. 'from PIL import Image')",
        "scikit_learn": "sklearn (e.g. 'import sklearn')",
    }

    @staticmethod
    def enrich_syntax_error_context(code: str, exc: SyntaxError) -> str:
        """
        Builds a rich, actionable diagnostic string from a SyntaxError,
        including exact line number, surrounding code snippet window,
        and targeted structural hints (e.g. unclosed try/except blocks, indentation, unclosed brackets).
        """
        lines = code.splitlines()
        err_line_num = exc.lineno or 1
        err_msg = exc.msg or "invalid syntax"

        # Build surrounding code snippet (up to 4 lines before and 3 lines after)
        start_idx = max(0, err_line_num - 4)
        end_idx = min(len(lines), err_line_num + 3)

        snippet_lines = []
        for idx in range(start_idx, end_idx):
            line_no = idx + 1
            line_content = lines[idx]
            prefix = ">" if line_no == err_line_num else " "
            snippet_lines.append(f"  {prefix} Line {line_no:3d}: {line_content}")

        snippet_str = "\n".join(snippet_lines)

        # Targeted structural diagnostic hint
        hint = ""
        msg_lower = err_msg.lower()
        if "expected 'except' or 'finally' block" in msg_lower or "expected an except block" in msg_lower:
            hint = (
                "\n\nDiagnostic Hint: An incomplete 'try:' block was detected without a matching 'except:' or 'finally:' clause. "
                "Ensure every 'try:' block is completed with its matching 'except Exception as e:' or 'finally:' block and proper indentation."
            )
        elif "indentation" in msg_lower or "indent" in msg_lower:
            hint = (
                "\n\nDiagnostic Hint: Indentation mismatch detected. Ensure 4-space indentation is consistently used "
                "inside all function definitions, classes, and code blocks."
            )
        elif "was never closed" in msg_lower or "unclosed" in msg_lower:
            hint = (
                "\n\nDiagnostic Hint: Unclosed parenthesis, bracket, or string literal detected. "
                "Ensure all '(', '[', '{', and quotes are properly paired and closed."
            )

        return f"SyntaxError: {err_msg} on line {err_line_num}\nCode snippet around error:\n{snippet_str}{hint}"

    @staticmethod
    def validate_python_syntax(code: str) -> ValidationResult:
        """Parses code with Python AST parser to catch any SyntaxError, IndentationError, or hallucinated import names."""
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in CodeValidator.KNOWN_INVALID_IMPORT_NAMES:
                            correct = CodeValidator.KNOWN_INVALID_IMPORT_NAMES[alias.name]
                            return ValidationResult(
                                is_valid=False,
                                error_message=f"Invalid import '{alias.name}'. The package must be imported as '{correct}'.",
                                error_line=node.lineno
                            )
                elif isinstance(node, ast.ImportFrom):
                    if node.module in CodeValidator.KNOWN_INVALID_IMPORT_NAMES:
                        correct = CodeValidator.KNOWN_INVALID_IMPORT_NAMES[node.module]
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"Invalid import from '{node.module}'. The package must be imported as '{correct}'.",
                            error_line=node.lineno
                        )
            return ValidationResult(is_valid=True)
        except SyntaxError as e:
            detailed_err = CodeValidator.enrich_syntax_error_context(code, e)
            return ValidationResult(
                is_valid=False,
                error_message=detailed_err,
                error_line=e.lineno
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f"AST Parse Error: {str(e)}"
            )

    @staticmethod
    def extract_python_symbols(code: str) -> Tuple[Set[str], Set[str]]:
        """Extracts top-level function names and class names from Python code."""
        functions = set()
        classes = set()
        try:
            tree = ast.parse(code)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    functions.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.add(node.name)
        except Exception:
            pass
        return functions, classes

    FRAMEWORK_RUNNER_SYMBOLS = {
        "InMemoryRunner", "AgentRunner", "StateGraph", "Crew", "AgentExecutor",
        "Workflow", "Flow", "Pipeline", "Swarm", "Orchestrator"
    }

    @staticmethod
    def extract_imported_symbols(code: str) -> Set[str]:
        """Extracts all imported module and symbol names from Python code."""
        symbols = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        symbols.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        symbols.add(node.module)
                    for alias in node.names:
                        symbols.add(alias.name)
        except Exception:
            pass
        return symbols

    @staticmethod
    def validate_business_logic_preservation(original_code: str, refactored_code: str) -> ValidationResult:
        """
        Ensures that top-level classes, functions, and framework runner components
        defined in original code are preserved in the refactored code.
        """
        orig_funcs, orig_classes = CodeValidator.extract_python_symbols(original_code)
        new_funcs, new_classes = CodeValidator.extract_python_symbols(refactored_code)

        missing_funcs = orig_funcs - new_funcs
        missing_classes = orig_classes - new_classes

        if missing_funcs:
            return ValidationResult(
                is_valid=False,
                error_message=f"Refactored code dropped required function(s): {', '.join(sorted(missing_funcs))}"
            )

        if missing_classes:
            return ValidationResult(
                is_valid=False,
                error_message=f"Refactored code dropped required class(es): {', '.join(sorted(missing_classes))}"
            )

        # Check for dropped imported names that are still referenced in refactored code (NameError guard)
        try:
            orig_imported_names = set()
            orig_tree = ast.parse(original_code)
            for node in ast.walk(orig_tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        orig_imported_names.add(alias.asname or alias.name)

            ref_imported_names = set()
            ref_defined_names = set()
            ref_referenced_names = set()
            ref_tree = ast.parse(refactored_code)
            for node in ast.walk(ref_tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        ref_imported_names.add(alias.asname or alias.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    ref_defined_names.add(node.name)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    ref_referenced_names.add(node.id)

            dropped_used_imports = (orig_imported_names & ref_referenced_names) - (ref_imported_names | ref_defined_names)
            if dropped_used_imports:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Refactored code dropped import(s) for symbol(s) still referenced in the code: {', '.join(sorted(dropped_used_imports))}. Preserve all required imports."
                )
        except Exception:
            pass

        # Framework runner and agent preservation check
        orig_imports = CodeValidator.extract_imported_symbols(original_code)
        new_imports = CodeValidator.extract_imported_symbols(refactored_code)
        
        dropped_runners = (orig_imports & CodeValidator.FRAMEWORK_RUNNER_SYMBOLS) - new_imports
        if dropped_runners:
            return ValidationResult(
                is_valid=False,
                error_message=f"Refactored code dropped native agent framework runner(s): {', '.join(sorted(dropped_runners))}. Preserve the original runner architecture."
            )

        # Module-level docstring preservation check
        try:
            tree_orig = ast.parse(original_code)
            tree_ref = ast.parse(refactored_code)
            orig_doc = ast.get_docstring(tree_orig)
            ref_doc = ast.get_docstring(tree_ref)
            if orig_doc and not ref_doc:
                return ValidationResult(
                    is_valid=False,
                    error_message="Refactored code dropped module-level docstring header. Preserve the original module documentation exactly."
                )
        except Exception:
            pass

        return ValidationResult(is_valid=True)

    @staticmethod
    def validate_decorator_definition_order(code: str) -> ValidationResult:
        """
        Ensures that any variable used in a top-level decorator (e.g. '@app.get', '@router.post', '@server.route')
        is defined (assigned, instantiated, or imported) before the first decorator reference in the module.
        Prevents runtime/import-time NameError (e.g., 'NameError: name 'app' is not defined').
        """
        try:
            tree = ast.parse(code)
            defined_top_level: Set[str] = set()
            standard_builtins = {
                "property", "staticmethod", "classmethod", "override",
                "abstractmethod", "final", "dataclass"
            }

            for stmt in tree.body:
                # 1. Track symbols defined at the module top level
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    for alias in stmt.names:
                        defined_top_level.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            defined_top_level.add(target.id)
                        elif isinstance(target, (ast.Tuple, ast.List)):
                            for elt in target.elts:
                                if isinstance(elt, ast.Name):
                                    defined_top_level.add(elt.id)
                elif isinstance(stmt, ast.AnnAssign):
                    if isinstance(stmt.target, ast.Name):
                        defined_top_level.add(stmt.target.id)
                elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # Check decorators on this definition
                    for dec in stmt.decorator_list:
                        dec_base = dec
                        while isinstance(dec_base, (ast.Call, ast.Attribute)):
                            if isinstance(dec_base, ast.Call):
                                dec_base = dec_base.func
                            elif isinstance(dec_base, ast.Attribute):
                                dec_base = dec_base.value
                        if isinstance(dec_base, ast.Name):
                            var_name = dec_base.id
                            if var_name not in standard_builtins and var_name not in dir(__builtins__) and var_name not in defined_top_level:
                                return ValidationResult(
                                    is_valid=False,
                                    error_message=(
                                        f"Decorator '@{var_name}...' on line {stmt.lineno} references variable '{var_name}' "
                                        f"before it is defined. In Python, '{var_name}' must be instantiated (e.g. '{var_name} = FastAPI(...)') "
                                        f"at the top level BEFORE any route decorator to prevent import-time NameError."
                                    ),
                                    error_line=stmt.lineno
                                )
                    # Add function/class name itself as defined
                    defined_top_level.add(stmt.name)
        except Exception:
            pass
        return ValidationResult(is_valid=True)

    @staticmethod
    def extract_imported_modules(code: str) -> Set[str]:
        """Extracts all imported module namespaces (e.g. 'google.adk.agents', 'os', 'openai') from Python code."""
        modules = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        modules.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        modules.add(node.module)
        except Exception:
            pass
        return modules

    @classmethod
    def validate_import_soundness(cls, original_code: str, refactored_code: str, file_extension: str = ".py") -> ValidationResult:
        """
        Dynamically verifies that all newly introduced imports in refactored code
        exist in the Python Standard Library, known package mappings, or on the PyPI registry.
        Rejects non-existent or hallucinated package imports (e.g. 'google_generativeai').
        """
        if file_extension in {".py", ".pyw"}:
            orig_modules = cls.extract_imported_modules(original_code)
            ref_modules = cls.extract_imported_modules(refactored_code)

            new_modules = ref_modules - orig_modules
            if not new_modules:
                return ValidationResult(is_valid=True)

            from apipatch.doc_hunter import DocHunter
            for mod in new_modules:
                if mod.startswith("."):
                    continue
                if not DocHunter.is_valid_registry_import(mod, ecosystem="python"):
                    return ValidationResult(
                        is_valid=False,
                        error_message=(
                            f"Hallucinated or non-existent import module detected: '{mod}'. "
                            f"This module does not exist in the Python Standard Library or PyPI registry. "
                            f"Do NOT invent non-existent package namespaces. Preserve the original import or use the official package."
                        )
                    )
        return ValidationResult(is_valid=True)

    @classmethod
    def validate_symbol_soundness(cls, original_code: str, refactored_code: str, file_extension: str = ".py") -> ValidationResult:
        """
        Dynamically tests whether attribute lookups on imported modules in refactored code
        (e.g., types.ToolContext, client.some_fake_attr) actually resolve without raising AttributeError.
        """
        if file_extension in {".py", ".pyw"}:
            from apipatch.test_runner import MicroSandboxEvaluator
            from apipatch.doc_hunter import DocHunter

            # 1. Ephemeral MicroSandbox evaluation
            sandbox_res = MicroSandboxEvaluator.evaluate_code_imports(refactored_code)
            if not sandbox_res.is_valid:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"Runtime symbol validation error: {sandbox_res.error_message}. Do not use non-existent attributes."
                )

            # 2. Dynamic AST attribute verification via DocHunter
            try:
                tree = ast.parse(refactored_code)
                import_map = {}
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            import_map[alias.asname or alias.name] = alias.name
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        for alias in node.names:
                            import_map[alias.asname or alias.name] = f"{node.module}.{alias.name}"

                local_param_names = set()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for arg in node.args.args + node.args.kwonlyargs:
                            local_param_names.add(arg.arg)
                        if node.args.vararg:
                            local_param_names.add(node.args.vararg.arg)
                        if node.args.kwarg:
                            local_param_names.add(node.args.kwarg.arg)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        alias = node.value.id
                        attr = node.attr
                        if alias in import_map and alias not in local_param_names:
                            mod_path = import_map[alias]
                            if not DocHunter.verify_module_symbol(mod_path, attr):
                                return ValidationResult(
                                    is_valid=False,
                                    error_message=(
                                        f"Invalid attribute '{alias}.{attr}': symbol '{attr}' is not part of '{mod_path}'. "
                                        f"Preserve the original context or import from the correct package."
                                    )
                                )
            except Exception:
                pass

        return ValidationResult(is_valid=True)

    @staticmethod
    def extract_js_symbols(code: str) -> Set[str]:
        """Extracts declared function, class, and component names from JS/TS code."""
        symbols = set()
        cleaned = re.sub(r'//.*?$|/\*.*?\*/', '', code, flags=re.MULTILINE | re.DOTALL)
        for m in re.finditer(r'(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)', cleaned):
            symbols.add(m.group(1))
        for m in re.finditer(r'(?:export\s+)?(?:default\s+)?class\s+([a-zA-Z0-9_$]+)', cleaned):
            symbols.add(m.group(1))
        for m in re.finditer(r'(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>', cleaned):
            symbols.add(m.group(1))
        return symbols

    @staticmethod
    def validate_generic_integrity(original_code: str, refactored_code: str) -> ValidationResult:
        """
        Structural and syntactical integrity check for JavaScript, TypeScript, JSX, TSX, etc.
        Robustly tokenizes code, correctly skipping:
          - Single-line comments (// ...)
          - Multi-line comments (/* ... */)
          - Single-quoted and double-quoted strings with escapes
          - Template literals (`...`) with recursive interpolation `${...}`
          - Regular expression literals (/.../flags)
        Accurately verifies balance of (), [], and {} across the file.
        """
        if not refactored_code or not refactored_code.strip():
            return ValidationResult(is_valid=False, error_message="Refactored code is empty")

        # Truncation guard: ensure refactored code isn't mysteriously truncated (>80% dropped on non-trivial files)
        if len(original_code) > 120 and len(refactored_code) < len(original_code) * 0.2:
            return ValidationResult(
                is_valid=False,
                error_message="Refactored code appears abnormally truncated compared to original source."
            )

        # JS/TS component and function preservation check
        orig_syms = CodeValidator.extract_js_symbols(original_code)
        ref_syms = CodeValidator.extract_js_symbols(refactored_code)
        missing_syms = orig_syms - ref_syms
        if missing_syms and len(orig_syms) > 0:
            return ValidationResult(
                is_valid=False,
                error_message=f"Refactored JS/TS code dropped required component/function: {', '.join(sorted(missing_syms))}"
            )

        code = refactored_code
        n = len(code)
        i = 0
        line = 1

        # Stack holds tuples: (expected_char, opening_line, type_tag)
        stack: List[Tuple[str, int, str]] = []
        template_depth = 0  # number of active template literal layers

        prev_non_ws = ""
        prev_word = ""

        while i < n:
            ch = code[i]
            if ch == '\n':
                line += 1
                i += 1
                continue

            # Skip whitespace
            if ch.isspace():
                i += 1
                continue

            # 1. Single-line comment: // ...
            if ch == '/' and i + 1 < n and code[i + 1] == '/':
                i += 2
                while i < n and code[i] != '\n':
                    i += 1
                continue

            # 2. Multi-line comment: /* ... */
            if ch == '/' and i + 1 < n and code[i + 1] == '*':
                start_line = line
                i += 2
                closed = False
                while i < n:
                    if code[i] == '\n':
                        line += 1
                    elif code[i] == '*' and i + 1 < n and code[i + 1] == '/':
                        i += 2
                        closed = True
                        break
                    i += 1
                if not closed:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Unclosed multi-line comment starting at line {start_line}",
                        error_line=start_line
                    )
                continue

            # 3. Single-quoted string: '...'
            if ch == "'":
                start_line = line
                i += 1
                closed = False
                while i < n:
                    c = code[i]
                    if c == '\n':
                        line += 1
                    elif c == '\\':
                        i += 2
                        continue
                    elif c == "'":
                        closed = True
                        i += 1
                        break
                    i += 1
                if not closed:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Unclosed single-quote string starting at line {start_line}",
                        error_line=start_line
                    )
                prev_non_ws = "'"
                prev_word = ""
                continue

            # 4. Double-quoted string: "..."
            if ch == '"':
                start_line = line
                i += 1
                closed = False
                while i < n:
                    c = code[i]
                    if c == '\n':
                        line += 1
                    elif c == '\\':
                        i += 2
                        continue
                    elif c == '"':
                        closed = True
                        i += 1
                        break
                    i += 1
                if not closed:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Unclosed double-quote string starting at line {start_line}",
                        error_line=start_line
                    )
                prev_non_ws = '"'
                prev_word = ""
                continue

            # 5. Template literal: `...`
            if ch == '`':
                start_line = line
                i += 1
                # Parse template literal contents until matching ` or ${
                closed = False
                while i < n:
                    c = code[i]
                    if c == '\n':
                        line += 1
                    elif c == '\\':
                        i += 2
                        continue
                    elif c == '`':
                        closed = True
                        i += 1
                        break
                    elif c == '$' and i + 1 < n and code[i + 1] == '{':
                        # Enter interpolated expression inside template literal
                        stack.append(('}', line, 'template_expr'))
                        i += 2
                        break
                    i += 1
                if not closed and (not stack or stack[-1][2] != 'template_expr'):
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Unclosed template literal starting at line {start_line}",
                        error_line=start_line
                    )
                prev_non_ws = '`'
                prev_word = ""
                continue

            # 6. Regex literal: /.../flags
            regex_preceders = {'=', '(', '[', '{', ':', ',', ';', '!', '?', '+', '-', '*', '&', '|', '^', '%', '~', '<', '>', '\n', ''}
            regex_keywords = {'return', 'yield', 'typeof', 'void', 'delete', 'throw', 'case', 'default', 'in', 'instanceof', 'of'}
            if ch == '/' and (prev_non_ws in regex_preceders or prev_word in regex_keywords):
                start_line = line
                i += 1
                in_char_class = False
                closed = False
                while i < n:
                    c = code[i]
                    if c == '\n':
                        break  # JS regex cannot span unescaped newlines
                    elif c == '\\':
                        i += 2
                        continue
                    elif c == '[' and not in_char_class:
                        in_char_class = True
                    elif c == ']' and in_char_class:
                        in_char_class = False
                    elif c == '/' and not in_char_class:
                        closed = True
                        i += 1
                        # Skip trailing flags (e.g. g, i, m, s, u, y, d)
                        while i < n and code[i].isalpha():
                            i += 1
                        break
                    i += 1
                if closed:
                    prev_non_ws = '/'
                    prev_word = ""
                    continue
                # If regex wasn't closed properly on single line, treat / as division operator below

            # 7. Brackets, Parentheses, Braces
            if ch in ('(', '[', '{'):
                stack.append((ch, line, 'bracket'))
                prev_non_ws = ch
                prev_word = ""
                i += 1
                continue

            if ch in (')', ']', '}'):
                if not stack:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Unmatched closing '{ch}' at line {line}.",
                        error_line=line
                    )
                expected_open, open_line, tag = stack.pop()
                if tag == 'template_expr' and ch == '}':
                    # Finished interpolated expression `${...}` inside template literal.
                    # Resume reading template literal until next ` or ${
                    closed_tmpl = False
                    while i + 1 < n:
                        i += 1
                        c = code[i]
                        if c == '\n':
                            line += 1
                        elif c == '\\':
                            i += 1
                            continue
                        elif c == '`':
                            closed_tmpl = True
                            i += 1
                            break
                        elif c == '$' and i + 1 < n and code[i + 1] == '{':
                            stack.append(('}', line, 'template_expr'))
                            i += 2
                            break
                    if not closed_tmpl and (not stack or stack[-1][2] != 'template_expr'):
                        return ValidationResult(
                            is_valid=False,
                            error_message=f"Unclosed template literal after expression at line {line}",
                            error_line=line
                        )
                    prev_non_ws = '`'
                    prev_word = ""
                    continue

                pairs = {')': '(', ']': '[', '}': '{'}
                if pairs.get(ch) != expected_open:
                    return ValidationResult(
                        is_valid=False,
                        error_message=f"Mismatched bracket: expected matching closing for '{expected_open}' (from line {open_line}), found '{ch}' at line {line}.",
                        error_line=line
                    )
                prev_non_ws = ch
                prev_word = ""
                i += 1
                continue

            # Record identifier characters for keyword checking
            if ch.isalnum() or ch == '_':
                start_w = i
                while i < n and (code[i].isalnum() or code[i] == '_'):
                    i += 1
                prev_word = code[start_w:i]
                prev_non_ws = code[i - 1]
                continue

            prev_non_ws = ch
            prev_word = ""
            i += 1

        if stack:
            unclosed_char, unclosed_line, tag = stack[-1]
            desc = "template expression" if tag == 'template_expr' else f"'{unclosed_char}'"
            return ValidationResult(
                is_valid=False,
                error_message=f"Structural integrity check failed: unclosed {desc} opened at line {unclosed_line}.",
                error_line=unclosed_line
            )

        return ValidationResult(is_valid=True)

    @classmethod
    def validate_model_name_integrity(cls, original_code: str, refactored_code: str) -> ValidationResult:
        """
        Guards against model identifier downgrades (e.g. Claude 4.5/3.7 -> 3.5, Gemini 3/2.5 -> 1.5)
        and client version downgrades (e.g. ClientV2 -> Client).
        """
        # 1. Guard against ClientV2 downgrade (AST-based so comments cannot bypass it)
        try:
            tree_orig = ast.parse(original_code)
            tree_ref = ast.parse(refactored_code)
            orig_has_v2 = any(
                (isinstance(n, ast.Attribute) and n.attr == "ClientV2") or (isinstance(n, ast.Name) and n.id == "ClientV2")
                for n in ast.walk(tree_orig)
            )
            ref_has_v2 = any(
                (isinstance(n, ast.Attribute) and n.attr == "ClientV2") or (isinstance(n, ast.Name) and n.id == "ClientV2")
                for n in ast.walk(tree_ref)
            )
            if orig_has_v2 and not ref_has_v2 and ("Client(" in refactored_code or ".Client(" in refactored_code):
                return ValidationResult(
                    is_valid=False,
                    error_message="Refactored code downgraded modern 'ClientV2' to legacy 'Client'. Preserve modern 'ClientV2'."
                )
        except Exception:
            if ("ClientV2" in original_code) and ("ClientV2" not in refactored_code) and ("Client(" in refactored_code or ".Client(" in refactored_code):
                return ValidationResult(
                    is_valid=False,
                    error_message="Refactored code downgraded modern 'ClientV2' to legacy 'Client'. Preserve modern 'ClientV2'."
                )

        # 2. Guard against modern model string downgrades (e.g. claude-sonnet-4-5, claude-4.5-sonnet, claude-3-7)
        modern_model_patterns = [
            r"claude-(?:sonnet-)?4[.-]5(?:-sonnet)?",
            r"claude-3[.-]7(?:-sonnet)?",
            r"gemini-3(?:[.-]\d+)?(?:-flash|-pro)?(?:-image)?",
            r"gemini-2\.5(?:-flash|-pro)?",
            r"gpt-5",
            r"qwen-3",
        ]

        for pat in modern_model_patterns:
            orig_matches = set(re.findall(pat, original_code, re.IGNORECASE))
            if orig_matches:
                ref_matches = set(re.findall(pat, refactored_code, re.IGNORECASE))
                if not ref_matches:
                    # Check if it was replaced with an older version
                    if any(legacy in refactored_code.lower() for legacy in ["claude-3-5", "claude-3.5", "gemini-1.5", "gpt-4"]):
                        return ValidationResult(
                            is_valid=False,
                            error_message=(
                                f"Model downgrade detected: original code specified a modern model matching '{list(orig_matches)[0]}', "
                                f"which was erroneously downgraded in refactored code. "
                                f"Preserve the exact modern model identifier specified in the original code."
                            )
                        )

        return ValidationResult(is_valid=True)

    FORMAT_SPEC_RE = re.compile(r"%(?:\((?P<key>[^)]+)\))?[#0\- +]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsap%]")

    @classmethod
    def validate_string_formatting_integrity(cls, refactored_code: str) -> ValidationResult:
        """
        Validates printf-style formatting in logging calls (logger.info, error, etc.)
        and modulo operator string format expressions to prevent runtime TypeError.
        """
        try:
            tree = ast.parse(refactored_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    method = None
                    arg_idx = 0
                    if isinstance(func, ast.Attribute) and func.attr in {
                        "debug", "info", "warning", "warn", "error", "critical", "exception"
                    }:
                        method = func.attr
                        arg_idx = 0
                    elif isinstance(func, ast.Attribute) and func.attr == "log" and len(node.args) >= 2:
                        method = "log"
                        arg_idx = 1

                    if method and len(node.args) > arg_idx:
                        first_arg = node.args[arg_idx]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            fmt = first_arg.value
                            specs = [
                                m.group(0)
                                for m in cls.FORMAT_SPEC_RE.finditer(fmt)
                                if m.group(0) != "%%" and not m.group("key")
                            ]
                            has_starred = any(isinstance(a, ast.Starred) for a in node.args[arg_idx + 1:])
                            if specs and not has_starred:
                                provided = len(node.args) - (arg_idx + 1)
                                if provided < len(specs):
                                    return ValidationResult(
                                        is_valid=False,
                                        error_message=(
                                            f"String formatting error in '{method}' call at line {node.lineno}: "
                                            f"format string expects {len(specs)} argument(s) ({', '.join(specs)}) "
                                            f"but only {provided} were provided. Preserve all original arguments."
                                        ),
                                        error_line=node.lineno,
                                    )
                elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
                    if isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
                        fmt = node.left.value
                        specs = [
                            m.group(0)
                            for m in cls.FORMAT_SPEC_RE.finditer(fmt)
                            if m.group(0) != "%%" and not m.group("key")
                        ]
                        if specs:
                            if isinstance(node.right, ast.Tuple):
                                has_starred = any(isinstance(elt, ast.Starred) for elt in node.right.elts)
                                if not has_starred and len(node.right.elts) < len(specs):
                                    return ValidationResult(
                                        is_valid=False,
                                        error_message=(
                                            f"String formatting error at line {node.lineno}: "
                                            f"format string expects {len(specs)} argument(s) ({', '.join(specs)}) "
                                            f"but tuple provides {len(node.right.elts)}. Preserve original arguments."
                                        ),
                                        error_line=node.lineno,
                                    )
                            elif len(specs) > 1 and not isinstance(node.right, (ast.Call, ast.Subscript, ast.Attribute, ast.Name)):
                                return ValidationResult(
                                    is_valid=False,
                                    error_message=(
                                        f"String formatting error at line {node.lineno}: "
                                        f"format string expects {len(specs)} argument(s) ({', '.join(specs)}) "
                                        f"but non-tuple single value provided."
                                    ),
                                    error_line=node.lineno,
                                )
        except Exception:
            pass
        return ValidationResult(is_valid=True)

    @staticmethod
    def validate_syntax_warnings(original_code: str, refactored_code: str) -> ValidationResult:
        """
        Checks for new SyntaxWarnings introduced by the LLM (e.g. invalid escape sequences '\\.').
        Supports Python 3.10/3.11 (where invalid escape sequence was DeprecationWarning)
        and Python 3.12+ (where it became SyntaxWarning).
        """
        import warnings
        orig_warnings = set()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", SyntaxWarning)
                warnings.simplefilter("always", DeprecationWarning)
                compile(original_code, "<string>", "exec")
                for w in caught:
                    msg = str(w.message)
                    if issubclass(w.category, SyntaxWarning) or "invalid escape sequence" in msg.lower():
                        orig_warnings.add(msg)
        except Exception:
            pass

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", SyntaxWarning)
                warnings.simplefilter("always", DeprecationWarning)
                compile(refactored_code, "<string>", "exec")
                for w in caught:
                    msg = str(w.message)
                    if issubclass(w.category, SyntaxWarning) or "invalid escape sequence" in msg.lower():
                        if msg not in orig_warnings:
                            return ValidationResult(
                                is_valid=False,
                                error_message=(
                                    f"SyntaxWarning introduced on line {w.lineno}: {msg}. "
                                    f"Use raw string literals (e.g. r'...' or r\"...\") for regular expressions and escape sequences."
                                ),
                                error_line=w.lineno,
                            )
        except Exception:
            pass

        return ValidationResult(is_valid=True)

    @staticmethod
    def strip_code_fences(code: str) -> str:
        """Strips accidental markdown code fences (```python ... ``` or ``` ...) from source code."""
        if not code or not isinstance(code, str):
            return code
        cleaned = code.strip()
        cleaned = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\r?\n?", "", cleaned)
        cleaned = re.sub(r"\r?\n?```\s*$", "", cleaned)
        return cleaned.strip()

    @classmethod
    def validate(cls, original_code: str, refactored_code: str, file_extension: str = ".py") -> ValidationResult:
        """Runs comprehensive multi-layer validation on refactored code."""
        refactored_code = cls.strip_code_fences(refactored_code)
        if file_extension in {".py", ".pyw"}:
            syntax_check = cls.validate_python_syntax(refactored_code)
            if not syntax_check.is_valid:
                return syntax_check

            warning_check = cls.validate_syntax_warnings(original_code, refactored_code)
            if not warning_check.is_valid:
                return warning_check

            logic_check = cls.validate_business_logic_preservation(original_code, refactored_code)
            if not logic_check.is_valid:
                return logic_check

            decorator_check = cls.validate_decorator_definition_order(refactored_code)
            if not decorator_check.is_valid:
                return decorator_check

            format_check = cls.validate_string_formatting_integrity(refactored_code)
            if not format_check.is_valid:
                return format_check

            model_check = cls.validate_model_name_integrity(original_code, refactored_code)
            if not model_check.is_valid:
                return model_check

            modernity_check = cls.validate_api_modernity_integrity(original_code, refactored_code)
            if not modernity_check.is_valid:
                return modernity_check

            import_check = cls.validate_import_soundness(original_code, refactored_code, file_extension)
            if not import_check.is_valid:
                return import_check

            symbol_check = cls.validate_symbol_soundness(original_code, refactored_code, file_extension)
            if not symbol_check.is_valid:
                return symbol_check

            return ValidationResult(is_valid=True)
        else:
            return cls.validate_generic_integrity(original_code, refactored_code)

    @classmethod
    def validate_api_modernity_integrity(cls, original_code: str, refactored_code: str) -> ValidationResult:
        """
        Guards against reverse migrations or downgrades of modern 2025/2026 SDK calls
        (e.g., Responses API -> Chat Completions, developer role -> system role, modern tokens).
        """
        # 1. Guard against OpenAI Responses API downgrade to Chat Completions
        if "responses.create" in original_code and "chat.completions.create" in refactored_code and "responses.create" not in refactored_code:
            return ValidationResult(
                is_valid=False,
                error_message=(
                    "API Downgrade detected: original code uses modern OpenAI Responses API ('responses.create'), "
                    "which was erroneously downgraded to 'chat.completions.create'. "
                    "Preserve modern Responses API calls."
                )
            )

        # 2. Guard against 'developer' role regression to 'system'
        if ('"role": "developer"' in original_code or "'role': 'developer'" in original_code) and \
           ('"role": "developer"' not in refactored_code and "'role': 'developer'" not in refactored_code):
            return ValidationResult(
                is_valid=False,
                error_message=(
                    "Parameter downgrade detected: 'developer' role is an intentional modern parameter. "
                    "Do not revert 'developer' to 'system'."
                )
            )

        # 3. Guard against max_output_tokens / max_completion_tokens downgrade to max_tokens
        for modern_tok in ["max_output_tokens", "max_completion_tokens"]:
            if modern_tok in original_code and modern_tok not in refactored_code and "max_tokens" in refactored_code:
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Token parameter downgrade detected: '{modern_tok}' is an intentional modern parameter. "
                        f"Preserve '{modern_tok}' instead of reverting to legacy 'max_tokens'."
                    )
                )

        # 4. Guard against reasoning model attribute downgrades (.reasoning_content / .reasoning -> .content)
        for r_attr in ["reasoning_content", "reasoning"]:
            if (f".{r_attr}" in original_code or f"['{r_attr}']" in original_code or f'["{r_attr}"]' in original_code) and \
               (f".{r_attr}" not in refactored_code and f"['{r_attr}']" not in refactored_code and f'["{r_attr}"]' not in refactored_code):
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Reasoning field regression detected: '{r_attr}' is an intentional modern attribute in reasoning models (e.g. DeepSeek-R1, OpenAI o1/o3). "
                        f"Do NOT replace or downgrade '{r_attr}' with generic 'content'."
                    )
                )

        return ValidationResult(is_valid=True)


