"""
ApiPatch Monorepo & Sub-Project Discovery Engine
Enables automatic discovery, partitioning, and scoping of multi-project repositories (Monorepos)
without requiring manual target path flags.
"""

import os
from typing import List, Dict, Set, Optional, Any, Tuple


MANIFEST_FILENAMES = (
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "setup.py",
    "Pipfile",
    "go.mod",
    "Cargo.toml"
)


class MonorepoManager:
    """
    Analyzes repository structure to discover independent sub-projects,
    resolve nearest ancestor manifests, and scope audits to distinct workspaces.
    """

    @staticmethod
    def normalize_path(path: str) -> str:
        """Normalizes file path using forward slashes and strips leading/trailing slashes."""
        return path.replace("\\", "/").strip("/")

    @classmethod
    def find_nearest_manifest(
        cls,
        file_path: str,
        manifest_paths: List[str],
        manifest_names: Tuple[str, ...] = MANIFEST_FILENAMES
    ) -> Optional[str]:
        """
        Given a file path and a list of all manifest paths in the repository,
        finds the closest ancestor manifest (e.g., inside the same directory or closest parent).
        Returns None if no ancestor manifest exists.
        """
        norm_file = cls.normalize_path(file_path)
        file_dir = os.path.dirname(norm_file)

        # Normalize candidate manifests
        norm_manifests = {cls.normalize_path(m): m for m in manifest_paths}

        # Climb directory tree from file_dir up to root
        current_dir = file_dir
        while True:
            for name in manifest_names:
                check_path = f"{current_dir}/{name}" if current_dir else name
                if check_path in norm_manifests:
                    return norm_manifests[check_path]

            if not current_dir:
                break
            # Move up one directory level
            parent = os.path.dirname(current_dir)
            if parent == current_dir:
                break
            current_dir = parent

        return None

    @classmethod
    def discover_subprojects_from_paths(
        cls,
        all_paths: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Scans a list of repository file paths (from Git tree or filesystem),
        discovers all subproject roots (directories containing a manifest),
        and returns a dictionary mapping subproject root directory -> metadata.
        """
        subprojects: Dict[str, Dict[str, Any]] = {}
        manifest_paths: List[str] = []

        for p in all_paths:
            norm = cls.normalize_path(p)
            base = os.path.basename(norm).lower()
            if base in MANIFEST_FILENAMES:
                manifest_paths.append(norm)

        for m in manifest_paths:
            subproject_dir = os.path.dirname(m)
            manifest_name = os.path.basename(m).lower()

            if subproject_dir not in subprojects:
                # Name of subproject is the folder name, or 'root' for top-level
                name = os.path.basename(subproject_dir) if subproject_dir else "root"
                subprojects[subproject_dir] = {
                    "dir": subproject_dir,
                    "name": name,
                    "manifests": [],
                    "files": []
                }

            subprojects[subproject_dir]["manifests"].append(m)

        # Assign code files to their nearest ancestor subproject
        for p in all_paths:
            norm = cls.normalize_path(p)
            base = os.path.basename(norm).lower()
            if base in MANIFEST_FILENAMES:
                continue

            nearest_m = cls.find_nearest_manifest(norm, manifest_paths)
            if nearest_m:
                subproject_dir = os.path.dirname(nearest_m)
                if subproject_dir in subprojects:
                    subprojects[subproject_dir]["files"].append(norm)

        return subprojects

    @classmethod
    def is_monorepo(cls, subprojects: Dict[str, Dict[str, Any]]) -> bool:
        """
        Returns True if the repository has multiple independent sub-projects
        or workspaces (at least 2 distinct project roots).
        """
        return len(subprojects) >= 2

    @classmethod
    def resolve_scoped_title(
        cls,
        modified_files: List[str],
        default_title: str = "[ApiPatch] Autonomous API Breaking Changes Migration"
    ) -> Tuple[str, Optional[str]]:
        """
        Examines modified files. If all modified files belong to a common subproject directory,
        returns an automatically scoped PR title and the subproject directory name.
        Example: ('[Rag_tutorials] [ApiPatch] Migrate deprecated APIs', 'rag_tutorials')
        """
        if not modified_files:
            return default_title, None

        normalized = [cls.normalize_path(f) for f in modified_files]
        first_segments = []

        for f in normalized:
            parts = f.split("/")
            if len(parts) > 1:
                first_segments.append(parts[0])
            else:
                first_segments.append("")

        # Check if all files share the exact same top-level folder
        if first_segments and len(set(first_segments)) == 1 and first_segments[0]:
            subproject_name = first_segments[0]
            prefix = f"[{subproject_name.capitalize()}] "
            clean_title = default_title
            if clean_title.startswith("[ApiPatch] "):
                scoped_title = f"{prefix}{clean_title}"
            else:
                scoped_title = f"{prefix}[ApiPatch] {clean_title}"
            return scoped_title, subproject_name

        return default_title, None

    @classmethod
    def get_file_subproject(
        cls,
        file_path: str,
        subprojects: Dict[str, Dict[str, Any]],
        manifest_paths: Optional[List[str]] = None
    ) -> str:
        """
        Determines which subproject directory a file belongs to.
        Returns subproject directory path, or "" (root) if not inside a subproject.
        """
        norm_file = cls.normalize_path(file_path)

        # 1. Direct check in subprojects' assigned files
        for s_dir, s_data in subprojects.items():
            if norm_file in s_data.get("files", []):
                return s_dir

        # 2. Nearest manifest ancestor lookup
        if manifest_paths:
            nearest_m = cls.find_nearest_manifest(norm_file, manifest_paths)
            if nearest_m:
                return os.path.dirname(nearest_m)

        # 3. Directory prefix check against known subproject dirs (longest prefix first)
        sorted_subdirs = sorted([d for d in subprojects.keys() if d], key=len, reverse=True)
        for s_dir in sorted_subdirs:
            if norm_file.startswith(s_dir + "/"):
                return s_dir

        return ""

    @classmethod
    def partition_audit_by_subproject(
        cls,
        audit_results: List[Dict[str, Any]],
        subprojects: Dict[str, Dict[str, Any]],
        manifest_paths: Optional[List[str]] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Groups audit_results by subproject directory.
        Returns Dict[subproject_dir -> list of audit result dicts].
        """
        partitions: Dict[str, List[Dict[str, Any]]] = {}
        for r in audit_results:
            f_path = r.get("file", "")
            s_dir = cls.get_file_subproject(f_path, subprojects, manifest_paths)
            if s_dir not in partitions:
                partitions[s_dir] = []
            partitions[s_dir].append(r)
        return partitions

