from __future__ import annotations

import json
import re
from typing import Dict, Tuple, List

# NEW — your OpenRouter client
from .llm_client import OpenRouterClient

# instantiate global client
client = OpenRouterClient()

from .diagram_fix import sanitize_id, sanitize_label


# --------------------------------------------------------------------
# Robust JSON extraction
# --------------------------------------------------------------------
def _safe_json_extract(text: str) -> Dict[str, str]:
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)

    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r'(\{[^{}]*"diagram"[^{}]*"summary"[^{}]*\})',
        r"(\{.*\})",
    ]

    for pat in patterns:
        m = re.search(pat, text, flags=re.DOTALL)
        if not m:
            continue
        candidate = m.group(1)
        try:
            return json.loads(candidate)
        except Exception:
            continue

    diagram_match = re.search(r'"diagram"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, flags=re.DOTALL)
    summary_match = re.search(r'"summary"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, flags=re.DOTALL)

    if diagram_match and summary_match:
        return {
            "diagram": diagram_match.group(1).replace('\\n', '\n').replace('\\"', '"'),
            "summary": summary_match.group(1).replace('\\n', '\n').replace('\\"', '"'),
        }

    raise ValueError("No valid JSON found in model output")


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _extract_functions_from_project(project_data: dict) -> List[dict]:
    if "functions" in project_data and project_data["functions"]:
        return project_data["functions"]

    if "relationships" in project_data:
        func_names = set()
        for rel in project_data["relationships"]:
            if rel.get("type") in ["calls", "invokes", "function_call", "uses", "renders", "call"]:
                if rel.get("source"):
                    func_names.add(rel["source"])
                if rel.get("target"):
                    func_names.add(rel["target"])
        if func_names:
            return [{"name": name, "file": "", "doc": ""} for name in sorted(func_names)]

    files = project_data.get("files", [])
    if files:
        return [{"name": f.get("path", "file").split("/")[-1], "file": f.get("path", ""), "doc": ""} for f in files]

    return []


def _detect_frontend_features(project_data: dict) -> dict:
    metadata = project_data.get("metadata", {})
    project_type = metadata.get("project_type", "")

    is_react = project_type == "React"
    is_vue = project_type == "Vue"
    is_frontend = is_react or is_vue or project_type in ["JavaScript/TypeScript", "Frontend"]

    component_count = sum(1 for f in project_data.get("functions", []) if f.get("type") == "component")

    return {
        "is_frontend": is_frontend,
        "is_react": is_react,
        "is_vue": is_vue,
        "project_type": project_type or "Unknown",
        "has_components": component_count > 0,
        "component_count": component_count,
    }


# --------------------------------------------------------------------
# Prompt formatting
# --------------------------------------------------------------------
def _format_prompt(project_data: dict) -> str:
    functions = _extract_functions_from_project(project_data)[:14]
    relationships = project_data.get("relationships", [])[:28]

    node_ids = {}
    node_lines = []

    for i, f in enumerate(functions):
        name = f.get("name", f"node{i}")
        nid = sanitize_id(name)
        node_ids[name] = nid
        node_lines.append(f'{nid}["{sanitize_label(name)[:32]}"]')

    edge_lines = []
    for rel in relationships:
        s, t = rel.get("source", ""), rel.get("target", "")
        if s in node_ids and t in node_ids:
            edge_lines.append(f"{node_ids[s]} --> {node_ids[t]}")

    sem = []
    for f in functions:
        name = f["name"]
        doc = f.get("doc", "") or "role implied by name"
        sem.append(f"- {name}: {doc[:90]}")
    sem_block = "\n".join(sem)

    prompt = f"""
You are a codebase-flow analyzer. Return ONLY valid JSON. No markdown, no commentary.

Input:
${file_contents}

Output format:
{
  "diagram": "<mermaid diagram capturing data flow + function interactions>",
  "summary": "<clear explanation of the repo structure and logic>"
}

Rules:
- Reply ONLY with JSON.
- "diagram" must be a valid Mermaid graph ("flowchart TD" or "graph TD").
- Never include backticks.
- Never include extra text before or after the JSON.
- If unsure, make reasonable assumptions but still return valid JSON.

"""

    return prompt.strip()


# --------------------------------------------------------------------
# Fallback generation
# --------------------------------------------------------------------
def _create_basic_diagram(project_data: dict) -> str:
    functions = _extract_functions_from_project(project_data)[:10]
    relationships = project_data.get("relationships", [])[:20]
    frontend_features = _detect_frontend_features(project_data)

    lines = ["flowchart TD"]
    nodes = {}

    if frontend_features["is_frontend"]:
        components = [f for f in functions if f.get("type") == "component"]
        functions_only = [f for f in functions if f.get("type") != "component"]

        for comp in components[:8]:
            nid = sanitize_id(comp["name"])
            label = sanitize_label(comp["name"])[:40]
            nodes[nid] = label
            lines.append(f'  {nid}["{label}"]')

        for func in functions_only[:4]:
            nid = sanitize_id(func["name"])
            label = sanitize_label(func["name"])[:40]
            nodes[nid] = label
            lines.append(f'  {nid}["{label}"]')

    else:
        for func in functions:
            nid = sanitize_id(func["name"])
            label = sanitize_label(func["name"])[:40]
            nodes[nid] = label
            lines.append(f'  {nid}["{label}"]')

    for rel in relationships[:15]:
        src = sanitize_id(rel.get("source", ""))
        tgt = sanitize_id(rel.get("target", ""))
        if src in nodes and tgt in nodes:
            lines.append(f"  {src} --> {tgt}")

    if len(lines) == 1:
        lines.extend([
            '  entry["Entry"]',
            '  process["Process"]',
            '  output["Output"]',
            "  entry --> process",
            "  process --> output",
        ])

    return "\n".join(lines)


def _create_basic_summary(project_data: dict) -> str:
    functions = _extract_functions_from_project(project_data)
    relationships = project_data.get("relationships", [])
    f = _detect_frontend_features(project_data)

    if f["is_frontend"]:
        if f["component_count"] > 0:
            return f"This {f['project_type']} project has {f['component_count']} components with {len(relationships)} connections. The diagram shows UI hierarchy and flow."
        return f"This {f['project_type']} project has {len(functions)} modules and {len(relationships)} connections."

    return f"This project contains {len(functions)} functions with {len(relationships)} execution paths."


def _fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _create_basic_diagram(project_data), _create_basic_summary(project_data)


# --------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------
def _validate_diagram(diagram: str) -> bool:
    if not diagram or not diagram.strip().startswith("flowchart"):
        return False
    lines = diagram.strip().splitlines()
    return len(lines) >= 3 and any("-->" in ln for ln in lines)


# --------------------------------------------------------------------
# MAIN: call OpenRouter
# --------------------------------------------------------------------
def generate_diagram_and_summary(project_data: dict) -> Tuple[str, str]:
    prompt = _format_prompt(project_data)

    raw_output = client.generate(prompt)

    payload = _safe_json_extract(raw_output)

    diagram = payload.get("diagram", "").strip()
    summary = payload.get("summary", "").strip()

    if not diagram or not summary:
        raise ValueError("Model returned incomplete JSON")

    return diagram, summary


# --------------------------------------------------------------------
# Process wrapper
# --------------------------------------------------------------------
def process_with_steps(project_data: dict) -> Tuple[str, str]:
    try:
        diagram, summary = generate_diagram_and_summary(project_data)
    except Exception as exc:
        print("⚠ LLM generation failed:", repr(exc))
        return _fallback_generation(project_data)

    if not _validate_diagram(diagram):
        print("⚠ Output validation failed after LLM step, using fallback")
        return _fallback_generation(project_data)

    return diagram, summary


def fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _fallback_generation(project_data)
