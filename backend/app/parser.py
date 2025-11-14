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

    MAX_FILES = 150

    # ==============================================================================
    def parse_zip(self, zip_path: Path) -> dict[str, Any]:
        extract_dir = zip_path.parent / "extracted"
        extract_dir.mkdir(exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        files_data = []
        file_index = {}

        for file_path in extract_dir.rglob("*"):

            if any(skip in {p.lower() for p in file_path.parts} for skip in self.SKIP_FOLDERS):
                continue
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue
            if len(files_data) >= self.MAX_FILES:
                break

            relative = file_path.relative_to(extract_dir).as_posix()

            if file_path.suffix.lower() == ".py":
                file_info = self._parse_python(file_path, relative)
            else:
                file_info = self._parse_js(file_path, relative)

            files_data.append(file_info)
            file_index[relative] = file_info

        all_functions = self._extract_all_functions(files_data)
        function_relationships = self._build_function_relationships(files_data, file_index)
        file_relationships = self._build_file_relationships(files_data, file_index)

        return {
            "files": files_data,
            "functions": all_functions,
            "relationships": function_relationships,
            "file_relationships": file_relationships,
        }

    # ==============================================================================
    # Helper: Get docstring or comment summary for semantic meaning
    def _extract_doc(self, node: ast.AST) -> str:
        doc = ast.get_docstring(node)
        if not doc:
            return ""
        return doc.strip().split("\n")[0][:120]

    # ==============================================================================
    def _extract_all_functions(self, files_data: list) -> list[dict]:
        all_functions = []

        for file_info in files_data:
            file_path = file_info["path"]

            for func in file_info.get("functions", []):
                name = func.get("name", "")
                if not name or name == "anonymous":
                    continue

                all_functions.append({
                    "name": name,
                    "file": file_path,
                    "start_line": func.get("start_line", 0),
                    "end_line": func.get("end_line", 0),
                    "doc": func.get("doc", ""),
                    "type": "function",
                })

        return all_functions

    # ==============================================================================
    def _build_function_relationships(self, files_data, file_index):
        relationships = []
        func_to_file = {}

        for file_info in files_data:
            file_path = file_info["path"]
            for func in file_info.get("functions", []):
                fn = func["name"]
                if fn not in func_to_file:
                    func_to_file[fn] = file_path

        for file_info in files_data:
            source_file = file_info["path"]
            source_functions = file_info.get("functions", [])
            calls = file_info.get("calls", [])

            for called_func in calls:
                if called_func not in func_to_file:
                    continue

                target_file = func_to_file[called_func]
                caller_candidates = [f["name"] for f in source_functions]

                if not caller_candidates and len(source_functions) == 1:
                    caller_candidates = [source_functions[0]["name"]]

                if not caller_candidates:
                    caller_candidates = [source_file.split("/")[-1]]

                for caller in caller_candidates:
                    relationships.append({
                        "source": caller,
                        "target": called_func,
                        "type": "calls",
                        "source_file": source_file,
                        "target_file": target_file,
                    })

        seen = set()
        unique = []
        for rel in relationships:
            key = (rel["source"], rel["target"])
            if key not in seen:
                seen.add(key)
                unique.append(rel)

        return unique

    # ==============================================================================
    def _build_file_relationships(self, files, file_index):
        relationships = []
        call_map = defaultdict(set)

        for file in files:
            src = file["path"]
            for imp in file["imports"]:
                relationships.append({"source": src, "target": imp, "type": "import"})
            for c in file["calls"]:
                call_map[src].add(c)

        for src, calls in call_map.items():
            for target_file, info in file_index.items():
                fnames = {fn["name"] for fn in info.get("functions", [])}
                if fnames.intersection(calls):
                    relationships.append({"source": src, "target": target_file, "type": "call"})

        return relationships

    # ==============================================================================
    def _parse_python(self, path: Path, relative: str) -> dict[str, Any]:
        try:
            source = path.read_text(encoding="utf-8")
        except:
            source = ""

        try:
            tree = ast.parse(source)
        except:
            return {"path": relative, "language": "python", "imports": [], "functions": [], "calls": []}

        functions = []
        calls = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                    "doc": self._extract_doc(node),
                })
            elif isinstance(node, ast.Call):
                name = self._get_call_name(node.func)
                if name:
                    calls.append(name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.extend(self._get_import_names(node))

        return {"path": relative, "language": "python", "imports": sorted(set(imports)),
                "functions": functions, "calls": sorted(set(calls))}

    # ==============================================================================
    def _parse_js(self, path: Path, relative: str) -> dict[str, Any]:
        try:
            source = path.read_text(encoding="utf-8")
        except:
            source = ""

        imports = [m.group("import").strip() for m in JS_IMPORT_RE.finditer(source)]
        functions = []
        lines = source.split("\n")

        for match in JS_FUNCTION_RE.finditer(source):
            name = match.group("name") or match.group("varname") or match.group("classname") or "anonymous"
            line = source[:match.start()].count("\n") + 1

            comments = []
            for line_back in reversed(lines[:line - 1][-5:]):
                stripped = line_back.strip()
                if stripped.startswith("//"):
                    comments.append(stripped[2:].strip())
                else:
                    break
            doc = " ".join(reversed(comments))[:120]

            functions.append({"name": name, "start_line": line, "end_line": line, "doc": doc})

        calls = [m.group("caller") for m in JS_CALL_RE.finditer(source)]

        return {"path": relative, "language": "javascript", "imports": sorted(set(imports)),
                "functions": functions, "calls": sorted(set(calls))}

    # ==============================================================================
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
