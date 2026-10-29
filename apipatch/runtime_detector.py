"""
ApiPatch Target Runtime & CI/CD Matrix Context Detector
Analyzes target repositories (local filesystem or remote file trees) to discover:
- CI/CD workflow matrices (.github/workflows/*.yml, *.yaml)
- Target Python versions (pyproject.toml requires-python, setup.cfg, .python-version, Dockerfile, etc.)
- Target Node.js versions (package.json engines.node, .nvmrc, .node-version, Dockerfile, etc.)
Synthesizes hard runtime constraints to ensure AI refactorings never introduce syntax,
APIs, or dependencies that break pinned CI/CD build matrices.
"""

import os
import re
import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass
class TargetRuntimeContext:
    python_versions: List[str] = field(default_factory=list)
    node_versions: List[str] = field(default_factory=list)
    ci_workflow_files: List[str] = field(default_factory=list)
    pinned_sources: List[str] = field(default_factory=list)
    raw_details: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_constraints(self) -> bool:
        return bool(self.python_versions or self.node_versions)

    def to_prompt_context(self) -> str:
        """
        Formats discovered runtime constraints into high-authority instructions
        for LLM prompt injection.
        """
        if not self.has_constraints:
            return ""

        lines = [
            "TARGET RUNTIME & CI/CD MATRIX CONSTRAINTS:",
        ]

        if self.python_versions:
            vers_str = ", ".join(self.python_versions)
            lines.append(f"- Python Target Version(s): {vers_str}")
            sources_str = ", ".join(self.pinned_sources) if self.pinned_sources else "CI / Project Manifests"
            lines.append(f"- Discovered From: {sources_str}")
            
            # Identify max version if detectable
            vers_clean = [re.sub(r"[^0-9.]", "", v) for v in self.python_versions]
            vers_clean = [v for v in vers_clean if v]
            if vers_clean:
                # Direct instruction against bleeding-edge features if pinned to <= 3.12
                if any(v.startswith("3.12") or v.startswith("3.11") or v.startswith("3.10") or v.startswith("3.9") for v in vers_clean):
                    if not any(v.startswith("3.13") or v.startswith("3.14") for v in vers_clean):
                        lines.append(
                            "- CRITICAL COMPATIBILITY: The project pins Python <= 3.12 in its CI/CD matrix. "
                            "Do NOT introduce Python 3.13+ features (e.g. copy.replace, typing.TypeIs without fallback, etc.). "
                            "Refactored code MUST execute cleanly across all pinned versions without breaking CI."
                        )
            lines.append("- BUILD SAFETY: Maintain full backward and forward compatibility with the project's pinned Python runtime matrix.")

        if self.node_versions:
            node_str = ", ".join(self.node_versions)
            lines.append(f"- Node.js Target Version(s): {node_str}")
            lines.append(
                f"- CRITICAL COMPATIBILITY: Code and modules MUST strictly support Node.js ({node_str}). "
                "Do NOT use ECMAScript or Node.js runtime features unsupported in these pinned engines."
            )

        return "\n".join(lines)


class TargetRuntimeDetector:
    """
    Scans project configurations and CI workflows to detect target runtimes.
    Works seamlessly on local filesystem paths or in-memory file mappings.
    """

    @classmethod
    def detect_from_directory(cls, project_dir: str) -> TargetRuntimeContext:
        """Inspects a local project directory."""
        project_dir = os.path.abspath(project_dir)
        ctx = TargetRuntimeContext()

        # 1. CI/CD Workflows (.github/workflows)
        workflows_dir = os.path.join(project_dir, ".github", "workflows")
        if os.path.isdir(workflows_dir):
            for fname in os.listdir(workflows_dir):
                if fname.endswith((".yml", ".yaml")):
                    wpath = os.path.join(workflows_dir, fname)
                    rel_name = os.path.join(".github", "workflows", fname).replace("\\", "/")
                    try:
                        with open(wpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        cls._extract_from_workflow_content(content, rel_name, ctx)
                    except Exception:
                        pass

        # 2. pyproject.toml
        pyproject_path = os.path.join(project_dir, "pyproject.toml")
        if os.path.isfile(pyproject_path):
            try:
                with open(pyproject_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                cls._extract_from_pyproject_content(content, "pyproject.toml", ctx)
            except Exception:
                pass

        # 3. .python-version / runtime.txt
        for pfile in (".python-version", "runtime.txt"):
            pver_path = os.path.join(project_dir, pfile)
            if os.path.isfile(pver_path):
                try:
                    with open(pver_path, "r", encoding="utf-8", errors="ignore") as f:
                        line = f.read().strip()
                    cls._extract_from_python_version_file(line, pfile, ctx)
                except Exception:
                    pass

        # 4. setup.cfg / setup.py
        setup_cfg = os.path.join(project_dir, "setup.cfg")
        if os.path.isfile(setup_cfg):
            try:
                with open(setup_cfg, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                cls._extract_from_setup_cfg_content(content, "setup.cfg", ctx)
            except Exception:
                pass

        # 5. Dockerfile
        dockerfile_path = os.path.join(project_dir, "Dockerfile")
        if os.path.isfile(dockerfile_path):
            try:
                with open(dockerfile_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                cls._extract_from_dockerfile_content(content, "Dockerfile", ctx)
            except Exception:
                pass

        # 6. package.json
        pkg_json_path = os.path.join(project_dir, "package.json")
        if os.path.isfile(pkg_json_path):
            try:
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                cls._extract_from_package_json_content(content, "package.json", ctx)
            except Exception:
                pass

        # 7. .nvmrc / .node-version
        for nfile in (".nvmrc", ".node-version"):
            nver_path = os.path.join(project_dir, nfile)
            if os.path.isfile(nver_path):
                try:
                    with open(nver_path, "r", encoding="utf-8", errors="ignore") as f:
                        line = f.read().strip()
                    cls._extract_from_node_version_file(line, nfile, ctx)
                except Exception:
                    pass

        cls._deduplicate_and_sort(ctx)
        return ctx

    @classmethod
    def detect_from_file_map(cls, file_map: Dict[str, str]) -> TargetRuntimeContext:
        """
        Inspects an in-memory dictionary of relative paths to contents.
        Useful for remote GitHub API inspection without cloning.
        """
        ctx = TargetRuntimeContext()

        for path, content in file_map.items():
            norm_path = path.replace("\\", "/").lower()
            if ".github/workflows/" in norm_path and (norm_path.endswith(".yml") or norm_path.endswith(".yaml")):
                cls._extract_from_workflow_content(content, path, ctx)
            elif norm_path.endswith("pyproject.toml"):
                cls._extract_from_pyproject_content(content, path, ctx)
            elif norm_path.endswith(".python-version") or norm_path.endswith("runtime.txt"):
                cls._extract_from_python_version_file(content.strip(), path, ctx)
            elif norm_path.endswith("setup.cfg"):
                cls._extract_from_setup_cfg_content(content, path, ctx)
            elif norm_path.endswith("dockerfile") or "/dockerfile" in norm_path:
                cls._extract_from_dockerfile_content(content, path, ctx)
            elif norm_path.endswith("package.json"):
                cls._extract_from_package_json_content(content, path, ctx)
            elif norm_path.endswith(".nvmrc") or norm_path.endswith(".node-version"):
                cls._extract_from_node_version_file(content.strip(), path, ctx)

        cls._deduplicate_and_sort(ctx)
        return ctx

    # ─── Internal Parsing Helpers ─────────────────────────────────────────────

    @classmethod
    def _extract_from_workflow_content(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Extracts python-version or node-version matrices from GitHub Actions YAML."""
        has_found = False

        # Match python-version: ["3.10", "3.11", "3.12"] or [3.10, 3.11] or multiline list
        # 1. Bracketed list: python-version:\s*\[([^\]]+)\]
        bracket_py = re.findall(r'python-version\s*:\s*\[([^\]]+)\]', content, re.IGNORECASE)
        for group in bracket_py:
            items = [re.sub(r'[\'"]', '', item).strip() for item in group.split(',')]
            for it in items:
                if it and re.match(r'^[0-9.]+', it):
                    ctx.python_versions.append(it)
                    has_found = True

        # 2. Single value: python-version:\s*['"]?([0-9.]+)['"]?
        single_py = re.findall(r'python-version\s*:\s*[\'"]?([0-9.]+(?:-dev)?)[\'"]?', content, re.IGNORECASE)
        for val in single_py:
            if val and val not in ctx.python_versions:
                ctx.python_versions.append(val)
                has_found = True

        # 3. Node version list or single: node-version:\s*\[([^\]]+)\]
        bracket_node = re.findall(r'node-version\s*:\s*\[([^\]]+)\]', content, re.IGNORECASE)
        for group in bracket_node:
            items = [re.sub(r'[\'"]', '', item).strip() for item in group.split(',')]
            for it in items:
                if it:
                    ctx.node_versions.append(it)
                    has_found = True

        single_node = re.findall(r'node-version\s*:\s*[\'"]?([0-9.x]+)[\'"]?', content, re.IGNORECASE)
        for val in single_node:
            if val and val not in ctx.node_versions:
                ctx.node_versions.append(val)
                has_found = True

        if has_found:
            ctx.ci_workflow_files.append(source_name)
            if source_name not in ctx.pinned_sources:
                ctx.pinned_sources.append(source_name)

    @classmethod
    def _extract_from_pyproject_content(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Extracts requires-python, poetry python, ruff target-version from pyproject.toml."""
        parsed = None
        if tomllib:
            try:
                parsed = tomllib.loads(content)
            except Exception:
                pass

        if parsed and isinstance(parsed, dict):
            # project.requires-python
            req_py = parsed.get("project", {}).get("requires-python")
            if req_py and isinstance(req_py, str):
                ctx.python_versions.append(req_py.strip())
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

            # tool.poetry.dependencies.python
            poetry_py = parsed.get("tool", {}).get("poetry", {}).get("dependencies", {}).get("python")
            if poetry_py and isinstance(poetry_py, str):
                ctx.python_versions.append(poetry_py.strip())
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

            # tool.ruff.target-version = "py312"
            ruff_target = parsed.get("tool", {}).get("ruff", {}).get("target-version")
            if ruff_target and isinstance(ruff_target, str):
                v = ruff_target.lower().replace("py", "")
                if len(v) == 3 and v.isdigit():
                    formatted_v = f"{v[0]}.{v[1:]}"
                    ctx.python_versions.append(formatted_v)
                    if source_name not in ctx.pinned_sources:
                        ctx.pinned_sources.append(source_name)
        else:
            # Regex fallback
            m_req = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', content)
            if m_req:
                ctx.python_versions.append(m_req.group(1).strip())
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

            m_ruff = re.search(r'target-version\s*=\s*["\']py?([0-9]+)["\']', content)
            if m_ruff:
                v = m_ruff.group(1)
                if len(v) == 3:
                    ctx.python_versions.append(f"{v[0]}.{v[1:]}")
                elif len(v) == 2:
                    ctx.python_versions.append(f"{v[0]}.{v[1]}")
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

    @classmethod
    def _extract_from_python_version_file(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Parses .python-version or runtime.txt."""
        first_line = content.splitlines()[0].strip() if content.splitlines() else ""
        if first_line:
            # Clean python-3.12.1 -> 3.12.1
            clean_ver = re.sub(r'^python-', '', first_line, flags=re.IGNORECASE).strip()
            if clean_ver and re.match(r'^[0-9.]+', clean_ver):
                ctx.python_versions.append(clean_ver)
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

    @classmethod
    def _extract_from_setup_cfg_content(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Extracts python_requires from setup.cfg."""
        m = re.search(r'python_requires\s*=\s*([^\r\n#]+)', content)
        if m:
            val = m.group(1).strip()
            if val:
                ctx.python_versions.append(val)
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

    @classmethod
    def _extract_from_dockerfile_content(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Extracts Python or Node base image versions from Dockerfile."""
        # FROM python:3.12-slim or FROM python:3.12
        py_match = re.findall(r'FROM\s+(?:--platform=\S+\s+)?python:([0-9.]+)', content, re.IGNORECASE)
        for ver in py_match:
            ctx.python_versions.append(ver)
            if source_name not in ctx.pinned_sources:
                ctx.pinned_sources.append(source_name)

        # FROM node:20-alpine or FROM node:18
        node_match = re.findall(r'FROM\s+(?:--platform=\S+\s+)?node:([0-9.x]+)', content, re.IGNORECASE)
        for ver in node_match:
            ctx.node_versions.append(ver)
            if source_name not in ctx.pinned_sources:
                ctx.pinned_sources.append(source_name)

    @classmethod
    def _extract_from_package_json_content(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Extracts engines.node from package.json."""
        try:
            data = json.loads(content)
            engines = data.get("engines", {})
            if isinstance(engines, dict):
                node_req = engines.get("node")
                if node_req and isinstance(node_req, str):
                    ctx.node_versions.append(node_req.strip())
                    if source_name not in ctx.pinned_sources:
                        ctx.pinned_sources.append(source_name)
        except Exception:
            pass

    @classmethod
    def _extract_from_node_version_file(cls, content: str, source_name: str, ctx: TargetRuntimeContext) -> None:
        """Parses .nvmrc or .node-version."""
        first_line = content.splitlines()[0].strip() if content.splitlines() else ""
        if first_line:
            clean_ver = re.sub(r'^v', '', first_line, flags=re.IGNORECASE).strip()
            if clean_ver:
                ctx.node_versions.append(clean_ver)
                if source_name not in ctx.pinned_sources:
                    ctx.pinned_sources.append(source_name)

    @classmethod
    def _deduplicate_and_sort(cls, ctx: TargetRuntimeContext) -> None:
        # Preserve order while deduplicating
        def _dedup(seq: List[str]) -> List[str]:
            seen: Set[str] = set()
            out: List[str] = []
            for x in seq:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        ctx.python_versions = _dedup(ctx.python_versions)
        ctx.node_versions = _dedup(ctx.node_versions)
        ctx.ci_workflow_files = _dedup(ctx.ci_workflow_files)
        ctx.pinned_sources = _dedup(ctx.pinned_sources)
