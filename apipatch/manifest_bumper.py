"""
ApiPatch Manifest Version Bumper
Automatically bumps package version specifications in requirements.txt,
pyproject.toml, and package.json to match modernized API code logic.
"""

import os
import re
import json
from typing import Dict, Set, Tuple, Optional, List, Any


# Standard minimum modern version constraints for major migrated packages
MODERN_VERSION_TARGETS: Dict[str, str] = {
    # Python ecosystem
    "pydantic": ">=2.0.0",
    "openai": ">=1.0.0",
    "google-genai": ">=0.1.0",
    "google.genai": ">=0.1.0",
    "google-generativeai": ">=0.8.0",
    "langchain": ">=0.2.0",
    "langchain-core": ">=0.2.0",
    "langchain-openai": ">=0.1.0",
    "langchain-anthropic": ">=0.1.0",
    "langchain-google-genai": ">=0.0.9",
    "langchain-community": ">=0.2.0",
    "stripe": ">=10.0.0",
    "supabase": ">=2.0.0",
    "fastapi": ">=0.110.0",
    "anthropic": ">=0.25.0",
    "pydantic-settings": ">=2.0.0",
    "sqlalchemy": ">=2.0.0",
    # JavaScript / TypeScript ecosystem
    "@supabase/supabase-js": "^2.0.0",
    "next": "^14.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "axios": "^1.6.0"
}

# Packages that replace or succeed older legacy packages during modernization
SUCCESSOR_PACKAGES: Dict[str, str] = {
    "google-generativeai": "google-genai",
    "google_generativeai": "google-genai",
    "google.generativeai": "google-genai",
}


class ManifestBumper:
    """
    Inspects and updates package manifest files (requirements.txt, pyproject.toml, package.json)
    to align declared dependency versions with the refactored code.
    """

    @classmethod
    def get_target_constraint(cls, lib_name: str) -> Optional[str]:
        """Returns the recommended modern version constraint for a library."""
        clean = lib_name.strip().lower()
        if clean in MODERN_VERSION_TARGETS:
            return MODERN_VERSION_TARGETS[clean]
        hyphenated = clean.replace("_", "-")
        if hyphenated in MODERN_VERSION_TARGETS:
            return MODERN_VERSION_TARGETS[hyphenated]
        underscored = clean.replace("-", "_")
        if underscored in MODERN_VERSION_TARGETS:
            return MODERN_VERSION_TARGETS[underscored]
        return None

    @classmethod
    def _parse_version_numbers(cls, ver_str: str) -> tuple:
        """Extracts numeric version tuple from a constraint string like '==2.10.6' or '>=2.0.0'."""
        digits = re.findall(r"\d+", ver_str)
        return tuple(int(x) for x in digits[:3]) if digits else (0,)

    @classmethod
    def _should_update_version(cls, existing: str, target: str) -> bool:
        """
        Returns False (do not update) if the existing constraint is already modern.
        Logic:
          - If existing uses == (exact pin) and its version >= target minimum → keep it, don't loosen.
          - If existing uses >= and is already >= target → keep it.
          - Otherwise allow the update.
        """
        existing = existing.strip()
        target = target.strip()
        try:
            target_min = cls._parse_version_numbers(target)
            if existing.startswith("=="):
                current = cls._parse_version_numbers(existing[2:])
                return current < target_min  # Only update if pinned version is TOO OLD
            elif existing.startswith(">="):
                current = cls._parse_version_numbers(existing[2:])
                return current < target_min  # Only update if floor is too low
        except Exception:
            pass
        return True  # Default: allow update if we can't parse

    @classmethod
    def bump_requirements_txt(
        cls,
        content: str,
        modernized_libraries: Set[str],
        auto_add_missing: bool = True
    ) -> Tuple[str, bool]:
        """
        Updates version requirements in requirements.txt content for modernized libraries.
        Automatically replaces predecessor packages with their modern successors (e.g. google-generativeai -> google-genai)
        and appends missing dependencies to prevent fresh-install ImportErrors.
        Returns (new_content, changed).
        """
        if not content or not content.strip() or not modernized_libraries:
            return content, False

        lines = content.splitlines(keepends=True)
        new_lines: List[str] = []
        changed = False
        seen_packages: Set[str] = set()

        normalized_libs = {lib.strip().lower() for lib in modernized_libraries if lib}
        normalized_libs.update({lib.replace("_", "-") for lib in normalized_libs})
        normalized_libs.update({lib.replace("-", "_") for lib in normalized_libs})
        normalized_libs.update({lib.replace(".", "-") for lib in normalized_libs})

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                new_lines.append(line)
                continue

            # Extract pkg name (before any version operators)
            parts = re.split(r"([><\=~;!@\[].*)", stripped, maxsplit=1)
            pkg_name = parts[0].strip()
            pkg_lower = pkg_name.lower()
            pkg_norm = pkg_lower.replace("_", "-")
            seen_packages.add(pkg_lower)
            seen_packages.add(pkg_norm)

            # ── 1. Successor Replacement Guard (e.g. google-generativeai -> google-genai) ──
            successor = SUCCESSOR_PACKAGES.get(pkg_norm) or SUCCESSOR_PACKAGES.get(pkg_lower)
            if successor and (pkg_norm in normalized_libs or successor in normalized_libs or successor.replace("-", "_") in normalized_libs):
                target_ver = cls.get_target_constraint(successor)
                if target_ver:
                    ending = "\n" if line.endswith("\n") else ""
                    new_lines.append(f"{successor}{target_ver}{ending}")
                    seen_packages.add(successor)
                    seen_packages.add(successor.replace("-", "_"))
                    changed = True
                    continue

            # ── 2. Standard Modernization Version Bump ──
            if pkg_lower in normalized_libs or pkg_norm in normalized_libs or pkg_lower.replace("-", "_") in normalized_libs:
                target_ver = cls.get_target_constraint(pkg_lower) or cls.get_target_constraint(pkg_norm)
                if target_ver:
                    existing_constraint = parts[1].strip() if len(parts) > 1 else ""

                    # Anti-Regression Guard: never loosen a modern pinned version
                    if existing_constraint and not cls._should_update_version(existing_constraint, target_ver):
                        new_lines.append(line)
                        continue

                    new_line_content = f"{pkg_name}{target_ver}"
                    ending = "\n" if line.endswith("\n") else ""
                    if existing_constraint != target_ver:
                        new_lines.append(f"{new_line_content}{ending}")
                        changed = True
                        continue

            new_lines.append(line)

        # ── 3. Auto-Append Missing Required Modern Dependencies ──
        if auto_add_missing and normalized_libs:
            for lib in sorted(normalized_libs):
                canonical = SUCCESSOR_PACKAGES.get(lib, lib.replace("_", "-").replace(".", "-"))
                if canonical in seen_packages or canonical.replace("-", "_") in seen_packages:
                    continue

                target_ver = cls.get_target_constraint(canonical)
                if target_ver:
                    if new_lines and not new_lines[-1].endswith("\n"):
                        new_lines[-1] += "\n"
                    new_lines.append(f"{canonical}{target_ver}\n")
                    seen_packages.add(canonical)
                    seen_packages.add(canonical.replace("-", "_"))
                    changed = True

        return "".join(new_lines), changed

    @classmethod
    def bump_package_json(cls, content: str, modernized_libraries: Set[str]) -> Tuple[str, bool]:
        """
        Updates version dependencies in package.json for modernized libraries.
        Returns (new_content, changed).
        """
        if not content or not modernized_libraries:
            return content, False

        try:
            data = json.loads(content)
        except Exception:
            return content, False

        changed = False
        normalized_libs = {lib.strip().lower() for lib in modernized_libraries if lib}

        for section in ("dependencies", "devDependencies"):
            if section in data and isinstance(data[section], dict):
                for pkg in list(data[section].keys()):
                    pkg_lower = pkg.lower()
                    if pkg_lower in normalized_libs:
                        target = cls.get_target_constraint(pkg_lower)
                        if target:
                            clean_target = target if target.startswith(("^", "~")) else f"^{target.lstrip('>=~=')}"
                            if data[section][pkg] != clean_target:
                                data[section][pkg] = clean_target
                                changed = True

        if changed:
            return json.dumps(data, indent=2) + "\n", True

        return content, False

    @classmethod
    def bump_pyproject_toml(cls, content: str, modernized_libraries: Set[str]) -> Tuple[str, bool]:
        """
        Updates dependencies list in pyproject.toml for modernized libraries.
        Returns (new_content, changed).
        """
        if not content or not modernized_libraries:
            return content, False

        lines = content.splitlines(keepends=True)
        new_lines: List[str] = []
        changed = False

        normalized_libs = {lib.strip().lower() for lib in modernized_libraries if lib}
        normalized_libs.update({lib.replace("_", "-") for lib in normalized_libs})
        normalized_libs.update({lib.replace(".", "-") for lib in normalized_libs})
        normalized_libs.update({lib.replace("-", "_") for lib in normalized_libs})

        for line in lines:
            # 1. Successor replacement (e.g. google-generativeai -> google-genai)
            successor_matched = False
            for pred, succ in SUCCESSOR_PACKAGES.items():
                if pred in normalized_libs or succ in normalized_libs or succ.replace("-", "_") in normalized_libs:
                    succ_ver = cls.get_target_constraint(succ)
                    if succ_ver:
                        pattern = re.compile(rf'("|\'){re.escape(pred)}([><=~;!@\[].*?)?("|\')', re.IGNORECASE)
                        if pattern.search(line):
                            quote = pattern.search(line).group(1)
                            replacement = f"{quote}{succ}{succ_ver}{quote}"
                            new_line = pattern.sub(replacement, line)
                            if new_line != line:
                                line = new_line
                                changed = True
                                successor_matched = True
                                break
            if successor_matched:
                new_lines.append(line)
                continue

            for lib in normalized_libs:
                target_ver = cls.get_target_constraint(lib)
                if not target_ver:
                    continue

                pattern = re.compile(rf'("|\'){re.escape(lib)}([><=~;!@\[].*?)?("|\')', re.IGNORECASE)
                if pattern.search(line):
                    quote = pattern.search(line).group(1)
                    replacement = f"{quote}{lib}{target_ver}{quote}"
                    new_line = pattern.sub(replacement, line)
                    if new_line != line:
                        line = new_line
                        changed = True
                        break

            new_lines.append(line)

        return "".join(new_lines), changed

    @classmethod
    def bump_local_manifests(
        cls,
        target_dir: str,
        modernized_libraries: Set[str],
        write: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Scans target_dir for requirements.txt, pyproject.toml, package.json
        and bumps them if needed. Returns list of modified manifest records.
        """
        target_dir = os.path.abspath(target_dir)
        records = []

        # Find all manifests in target_dir (supporting root and nested monorepo subprojects)
        candidate_manifests = []
        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build")]
            for f in files:
                if f.lower() in ("requirements.txt", "pyproject.toml", "package.json"):
                    candidate_manifests.append(os.path.join(root, f))

        for manifest_path in candidate_manifests:
            base = os.path.basename(manifest_path).lower()
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    content = f.read()

                if base == "requirements.txt":
                    new_c, changed = cls.bump_requirements_txt(content, modernized_libraries)
                elif base == "pyproject.toml":
                    new_c, changed = cls.bump_pyproject_toml(content, modernized_libraries)
                elif base == "package.json":
                    new_c, changed = cls.bump_package_json(content, modernized_libraries)
                else:
                    changed = False

                if changed:
                    if write:
                        with open(manifest_path, "w", encoding="utf-8") as f:
                            f.write(new_c)
                    records.append({"file": manifest_path, "manifest": base, "content": new_c})
            except Exception:
                pass

        return records
