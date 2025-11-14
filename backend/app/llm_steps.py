from __future__ import annotations

import json
import re
from typing import Dict, Tuple, List

from .ollama import OllamaClient
from .diagram_fix import sanitize_id, sanitize_label

_CLIENT = OllamaClient()


def _select_client(active: OllamaClient | None) -> OllamaClient:
    return active or _CLIENT


# --------------------------------------------------------------------
# Robust JSON extraction with fallbacks (keeps previous behavior)
# --------------------------------------------------------------------
def _safe_json_extract(text: str) -> Dict[str, str]:
    """Extract JSON payload with several fallback strategies."""
    # remove control characters that often break parsers
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)

    # Strategy 1: fenced JSON blocks or direct JSON object
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
            # try next pattern
            continue

    # Strategy 2: manual field extraction of quoted fields
    diagram_match = re.search(r'"diagram"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, flags=re.DOTALL)
    summary_match = re.search(r'"summary"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, flags=re.DOTALL)
    if diagram_match and summary_match:
        return {
            "diagram": diagram_match.group(1).replace('\\n', '\n').replace('\\"', '"'),
            "summary": summary_match.group(1).replace('\\n', '\n').replace('\\"', '"'),
        }

    raise ValueError("No valid JSON found in model output")


# --------------------------------------------------------------------
# Helpers to extract functions list from project_data (backwards compat)
# --------------------------------------------------------------------
def _extract_functions_from_project(project_data: dict) -> List[dict]:
    """Return a list of functions with metadata. Backwards compatible with older shapes."""
    if "functions" in project_data and project_data["functions"]:
        return project_data["functions"]

    # Fallback: try to infer function names from relationships
    if "relationships" in project_data:
        func_names = set()
        for rel in project_data["relationships"]:
            rel_type = rel.get("type", "")
            if rel_type in ["calls", "invokes", "function_call", "uses", "renders", "call"]:
                source = rel.get("source", "")
                target = rel.get("target", "")
                if source:
                    func_names.add(source)
                if target:
                    func_names.add(target)
        if func_names:
            return [{"name": name, "file": "", "doc": ""} for name in sorted(func_names)]

    # Last resort: use file names
    files = project_data.get("files", [])
    if files:
        return [{"name": f.get("path", "file").split("/")[-1], "file": f.get("path", ""), "doc": ""} for f in files]

    return []


# --------------------------------------------------------------------
# Detect frontend features (React/Vue) - unchanged logic but safe
# --------------------------------------------------------------------
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
# Prompt formatting — now includes concise function semantics (doc/comments)
# --------------------------------------------------------------------
def _format_prompt(project_data: dict) -> str:
    """Compact deep-architecture prompt optimized for Mistral-7B."""
    functions = _extract_functions_from_project(project_data)[:14]
    relationships = project_data.get("relationships", [])[:28]

    # nodes
    node_ids = {}
    node_lines = []
    for i, f in enumerate(functions):
        name = f.get("name", f"node{i}")
        nid = sanitize_id(name)
        node_ids[name] = nid
        node_lines.append(f'{nid}["{sanitize_label(name)[:32]}"]')

    # edges
    edge_lines = []
    for rel in relationships:
        s, t = rel.get("source", ""), rel.get("target", "")
        if s in node_ids and t in node_ids:
            edge_lines.append(f"{node_ids[s]} --> {node_ids[t]}")

    # semantics short
    sem = []
    for f in functions:
        name = f["name"]
        doc = f.get("doc", "")
        if not doc:
            doc = "role implied by name"
        sem.append(f"- {name}: {doc[:90]}")
    sem_block = "\n".join(sem)

    prompt = f"""
ONLY OUTPUT VALID JSON. NOTHING ELSE.

FORMAT:
{{"diagram": "flowchart LR\\n...", "summary": "..." }}

RULES:
- Diagram must start with: flowchart LR
- Use 6–12 nodes
- Use 4–15 edges
- Build a DEEP pipeline (not star layout)
- Prefer sequential flow A --> B --> C --> D
- Order nodes using call dependencies and semantic roles
- Infer logical stages from relationships and purpose implied in names
- Use only given node ids

FUNCTION SEMANTICS:
{sem_block}

AVAILABLE NODES:
{chr(10).join(node_lines)}

RELATIONSHIPS (follow flows logically):
{chr(10).join(edge_lines)}

GOAL:
Produce the most meaningful layered architecture showing data/control flow.
Focus on depth and stage progression. No invented nodes. No explanations.

Return ONLY a JSON object now.
"""
    return prompt.strip()



# --------------------------------------------------------------------
# Create a simple fallback mermaid diagram if the LLM fails
# --------------------------------------------------------------------
def _create_basic_diagram(project_data: dict) -> str:
    functions = _extract_functions_from_project(project_data)[:10]
    relationships = project_data.get("relationships", [])[:20]
    frontend_features = _detect_frontend_features(project_data)

    lines = ["flowchart TD"]
    nodes: Dict[str, str] = {}

    if frontend_features["is_frontend"]:
        components = [f for f in functions if f.get("type") == "component"]
        functions_only = [f for f in functions if f.get("type") != "component"]

        for comp in components[:8]:
            name = comp.get("name", "")
            if not name:
                continue
            nid = sanitize_id(name)
            label = sanitize_label(name)[:40]
            if nid in nodes:
                continue
            nodes[nid] = label
            lines.append(f'  {nid}["{label}"]')

        for func in functions_only[:4]:
            name = func.get("name", "")
            if not name:
                continue
            nid = sanitize_id(name)
            label = sanitize_label(name)[:40]
            if nid in nodes:
                continue
            nodes[nid] = label
            lines.append(f'  {nid}["{label}"]')
    else:
        for func in functions:
            name = func.get("name", "")
            if not name:
                continue
            nid = sanitize_id(name)
            label = sanitize_label(name)[:40]
            if nid in nodes:
                continue
            nodes[nid] = label
            lines.append(f'  {nid}["{label}"]')

    for relation in relationships[:15]:
        src = sanitize_id(relation.get("source", ""))
        tgt = sanitize_id(relation.get("target", ""))
        if src in nodes and tgt in nodes:
            lines.append(f"  {src} --> {tgt}")

    # minimal fallback graph
    if len(lines) == 1:
        if frontend_features["is_react"]:
            lines.extend([
                '  App["App"]',
                '  Page["Page"]',
                '  UI["UI"]',
                '  App --> Page',
                '  Page --> UI',
            ])
        else:
            lines.extend([
                '  entry["Entry"]',
                '  process["Process"]',
                '  output["Output"]',
                "  entry --> process",
                "  process --> output",
            ])

    return "\n".join(lines)


# --------------------------------------------------------------------
# Create a short fallback summary
# --------------------------------------------------------------------
def _create_basic_summary(project_data: dict) -> str:
    functions = _extract_functions_from_project(project_data)
    relationships = project_data.get("relationships", [])
    frontend_features = _detect_frontend_features(project_data)

    func_count = len(functions)
    relation_count = len(relationships)
    project_type = frontend_features["project_type"]

    if frontend_features["is_frontend"]:
        comp_count = frontend_features["component_count"]
        if comp_count > 0:
            return f"This {project_type} project has {comp_count} components and {relation_count} connections. The diagram shows component hierarchy and data flow. Use it to locate main UI boundaries and data flow."
        else:
            return f"This {project_type} project has {func_count} modules and {relation_count} connections. The diagram highlights module relationships and execution flow."
    else:
        return f"This project contains {func_count} functions with {relation_count} execution paths. The diagram illustrates call flow and high-level dependencies."


def _fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _create_basic_diagram(project_data), _create_basic_summary(project_data)


# --------------------------------------------------------------------
# Validate a mermaid flowchart (simple checks)
# --------------------------------------------------------------------
def _validate_diagram(diagram: str) -> bool:
    if not diagram or not diagram.strip().startswith("flowchart"):
        return False
    lines = diagram.strip().splitlines()
    if len(lines) < 3:
        return False
    has_nodes = any("[" in ln and "]" in ln for ln in lines[1:])
    has_edges = any("-->" in ln for ln in lines)
    return has_nodes and has_edges


# --------------------------------------------------------------------
# Main LLM call + postprocessing
# --------------------------------------------------------------------
def generate_diagram_and_summary(
    project_data: dict,
    ollama_client: OllamaClient | None = None,
) -> Tuple[str, str]:
    client = _select_client(ollama_client)
    prompt = _format_prompt(project_data)

    # helpful debug: warn if prompt is big
    if len(prompt) > 4000:
        print(f"⚠ Warning: prompt length {len(prompt)} chars (may be long for tiny models)")

    raw = client.generate(prompt)
    payload = _safe_json_extract(raw)

    diagram = payload.get("diagram", "").strip()
    summary = payload.get("summary", "").strip()

    if not _validate_diagram(diagram):
        raise ValueError("Invalid diagram structure returned by model")

    return diagram, summary


# --------------------------------------------------------------------
# High level process wrapper with fallbacks and validation
# --------------------------------------------------------------------
def process_with_steps(
    project_data: dict,
    ollama_client: OllamaClient | None = None,
) -> Tuple[str, str]:
    try:
        diagram, summary = generate_diagram_and_summary(project_data, ollama_client)
    except Exception as exc:
        print("⚠ LLM generation failed:", repr(exc))
        diagram, summary = _fallback_generation(project_data)
        return diagram, summary

    # final safety
    if not diagram or not summary or not _validate_diagram(diagram):
        print("⚠ Output validation failed after LLM step, using fallback")
        diagram, summary = _fallback_generation(project_data)

    return diagram, summary


# simple alias kept for compatibility
def fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _fallback_generation(project_data)
