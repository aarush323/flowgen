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

        # NEW: Build function-level data
        all_functions = self._extract_all_functions(files_data)
        function_relationships = self._build_function_relationships(files_data, file_index)
        
        # Keep old file-level relationships for backward compatibility
        file_relationships = self._build_file_relationships(files_data, file_index)

        return {
            "files": files_data,
            "functions": all_functions,  # NEW: Function list
            "relationships": function_relationships,  # NEW: Function-level calls
            "file_relationships": file_relationships,  # OLD: For backward compat
        }

    # ======================================================================
    # NEW: EXTRACT ALL FUNCTIONS WITH METADATA
    # ======================================================================
    def _extract_all_functions(self, files_data: list[dict]) -> list[dict]:
        """Extract all functions from all files with their metadata."""
        all_functions = []
        
        for file_info in files_data:
            file_path = file_info["path"]
            
            for func in file_info.get("functions", []):
                func_name = func.get("name", "")
                if not func_name or func_name == "anonymous":
                    continue
                
                all_functions.append({
                    "name": func_name,
                    "file": file_path,
                    "start_line": func.get("start_line", 0),
                    "end_line": func.get("end_line", 0),
                    "type": "function",
                })
        
        return all_functions

    # ======================================================================
    # NEW: BUILD FUNCTION-TO-FUNCTION RELATIONSHIPS
    # ======================================================================
    def _build_function_relationships(self, files_data, file_index):
        """Build function-level call graph."""
        relationships = []
        
        # Build a global function registry: func_name -> file_path
        func_to_file: dict[str, str] = {}
        for file_info in files_data:
            file_path = file_info["path"]
            for func in file_info.get("functions", []):
                func_name = func.get("name", "")
                if func_name and func_name != "anonymous":
                    # If duplicate, keep first occurrence
                    if func_name not in func_to_file:
                        func_to_file[func_name] = file_path
        
        # For each file, match calls to known functions
        for file_info in files_data:
            source_file = file_info["path"]
            calls = file_info.get("calls", [])
            source_functions = [f["name"] for f in file_info.get("functions", [])]
            
            # For each call made in this file
            for called_func in calls:
                if not called_func or called_func == "anonymous":
                    continue
                
                # Check if this is a known function
                if called_func in func_to_file:
                    target_file = func_to_file[called_func]
                    
                    # Try to determine which function in source_file made this call
                    # For now, we'll use a heuristic: if file has 1 function, that's the caller
                    # Otherwise, we'll create relationships for all functions in the file
                    
                    if len(source_functions) == 1:
                        # Single function file - clear caller
                        caller = source_functions[0]
                        relationships.append({
                            "source": caller,
                            "target": called_func,
                            "type": "calls",
                            "source_file": source_file,
                            "target_file": target_file,
                        })
                    elif len(source_functions) > 1:
                        # Multiple functions - create edges from each
                        # This is conservative but shows all possible flows
                        for caller in source_functions:
                            relationships.append({
                                "source": caller,
                                "target": called_func,
                                "type": "calls",
                                "source_file": source_file,
                                "target_file": target_file,
                            })
                    else:
                        # No functions defined, use file name as caller
                        file_name = source_file.split("/")[-1].replace(".py", "").replace(".js", "")
                        relationships.append({
                            "source": file_name,
                            "target": called_func,
                            "type": "calls",
                            "source_file": source_file,
                            "target_file": target_file,
                        })
        
        # Deduplicate relationships
        seen = set()
        unique_relationships = []
        for rel in relationships:
            key = (rel["source"], rel["target"], rel["type"])
            if key not in seen:
                seen.add(key)
                unique_relationships.append(rel)
        
        return unique_relationships

    # ======================================================================
    # OLD: FILE-LEVEL RELATIONSHIPS (BACKWARD COMPATIBILITY)
    # ======================================================================
    def _build_file_relationships(self, files, file_index):
        """Original file-level relationship builder (kept for backward compat)."""
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
    # PYTHON PARSER (ENHANCED)
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
            # function definitions (with line numbers)
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": node.end_lineno or node.lineno,
                })
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
            # Approximate line number
            line_num = source[:match.start()].count('\n') + 1
            functions.append({
                "name": name,
                "start_line": line_num,
                "end_line": line_num,  # Approximate
            })

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