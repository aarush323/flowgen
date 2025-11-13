from __future__ import annotations

import ast
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any


# Regex for basic JS parsing
JS_IMPORT_RE = re.compile(
    r"""(?P<import>
        ^\s*import\s+[^;]+;\s*$|
        ^\s*const\s+\w+\s*=\s*require\([^)]*\);\s*$
    )""",
    re.MULTILINE | re.VERBOSE,
)

JS_FUNCTION_RE = re.compile(
    r"""(?P<func>
        ^\s*function\s+(?P<name>\w+)\s*\( |
        ^\s*(?:const|let|var)\s+(?P<varname>\w+)\s*=\s*\(.*?\)\s*=> |
        ^\s*(?P<classname>\w+)\s*:\s*function\s*\(
    )""",
    re.MULTILINE | re.VERBOSE,
)

JS_CALL_RE = re.compile(r"\b(?P<caller>\w+)\s*\(", re.MULTILINE)


class ProjectParser:
    SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx"}

    # Folders that must NEVER be parsed
    SKIP_FOLDERS = {
        ".venv", "venv", "env",
        "__pycache__",
        "node_modules",
        "dist", "build",
        "lib", "site-packages",
        ".git", ".github",
        "datasets", "data",
        "cache", "logs",
        "chunks", "embeddings",
        "static", "public",
    }

    # Absolute safety limit → prevents prompt explosion
    MAX_FILES = 150

    def parse_zip(self, zip_path: Path) -> dict[str, Any]:
        extract_dir = zip_path.parent / "extracted"
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        files_data: list[dict[str, Any]] = []
        file_index: dict[str, dict[str, Any]] = {}

        for file_path in extract_dir.rglob("*"):

            # Skip blacklisted directories
            if any(skip in {p.lower() for p in file_path.parts} for skip in self.SKIP_FOLDERS):
                continue

            if not file_path.is_file():
                continue

            if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue

            # Enforce max-files limit
            if len(files_data) >= self.MAX_FILES:
                break

            relative = file_path.relative_to(extract_dir).as_posix()

            if file_path.suffix.lower() == ".py":
                file_info = self._parse_python(file_path, relative)
            else:
                file_info = self._parse_js(file_path, relative)

            files_data.append(file_info)
            file_index[relative] = file_info

        # Relationships between files
        relationships = self._build_relationships(files_data, file_index)

        return {
            "files": files_data,
            "relationships": relationships,
        }

    # ======================================================================
    # PYTHON PARSER
    # ======================================================================
    def _parse_python(self, path: Path, relative: str) -> dict[str, Any]:
        try:
            source = path.read_text(encoding="utf-8")
        except:
            source = ""

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {
                "path": relative,
                "language": "python",
                "imports": [],
                "functions": [],
                "calls": [],
            }

        functions = []
        calls = []
        imports = []

        for node in ast.walk(tree):
            # function definitions
            if isinstance(node, ast.FunctionDef):
                functions.append({"name": node.name})
            # function calls
            elif isinstance(node, ast.Call):
                name = self._get_call_name(node.func)
                if name:
                    calls.append(name)
            # imports
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.extend(self._get_import_names(node))

        return {
            "path": relative,
            "language": "python",
            "imports": sorted(set(imports)),
            "functions": functions,
            "calls": sorted(set(calls)),
        }

    # ======================================================================
    # JS PARSER
    # ======================================================================
    def _parse_js(self, path: Path, relative: str) -> dict[str, Any]:
        try:
            source = path.read_text(encoding="utf-8")
        except:
            source = ""

        imports = [match.group("import").strip() for match in JS_IMPORT_RE.finditer(source)]

        # functions
        functions = []
        for match in JS_FUNCTION_RE.finditer(source):
            name = (
                match.group("name")
                or match.group("varname")
                or match.group("classname")
                or "anonymous"
            )
            functions.append({"name": name})

        # calls
        calls = [match.group("caller") for match in JS_CALL_RE.finditer(source)]

        return {
            "path": relative,
            "language": "javascript",
            "imports": sorted(set(imports)),
            "functions": functions,
            "calls": sorted(set(calls)),
        }

    # ======================================================================
    # RELATIONSHIP BUILDER
    # ======================================================================
    def _build_relationships(self, files, file_index):
        relationships = []
        call_map: dict[str, set[str]] = defaultdict(set)

        # Imports → direct edges
        for file in files:
            src = file["path"]
            for imp in file["imports"]:
                relationships.append({
                    "source": src,
                    "target": imp,
                    "type": "import",
                })

            # collect calls
            for c in file["calls"]:
                call_map[src].add(c)

        # match calls → to file functions
        for src, calls in call_map.items():
            for target_file, info in file_index.items():
                function_names = {fn["name"] for fn in info.get("functions", [])}
                if function_names.intersection(calls):
                    relationships.append({
                        "source": src,
                        "target": target_file,
                        "type": "call",
                    })

        return relationships

    # ======================================================================
    # HELPERS
    # ======================================================================
    @staticmethod
    def _get_call_name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    @staticmethod
    def _get_import_names(node):
        if isinstance(node, ast.Import):
            return [alias.name for alias in node.names]
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            return [f"{module}.{alias.name}".strip(".") for alias in node.names]
        return []


def serialize_project(project_data: dict[str, Any]) -> str:
    return json.dumps(project_data, indent=2)


__all__ = ["ProjectParser", "serialize_project"]
