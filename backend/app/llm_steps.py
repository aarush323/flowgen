"""
Enhanced LLM processing optimized for small models like Qwen 3B.
Drop-in replacement - no changes needed in main.py
"""

from __future__ import annotations

import json
import re
from typing import Dict, Tuple

from .ollama import OllamaClient
from .diagram_fix import sanitize_id, sanitize_label


_CLIENT = OllamaClient()


def _select_client(active: OllamaClient | None) -> OllamaClient:
    return active or _CLIENT


def _safe_json_extract(text: str) -> Dict[str, str]:
    """Enhanced JSON extraction with multiple fallback strategies"""
    # Remove control characters
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)

    # Strategy 1: Standard patterns
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r'(\{[^{}]*"diagram"[^{}]*"summary"[^{}]*\})',
        r"(\{.*\})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.DOTALL)
        if not match:
            continue
        payload = match.group(1)
        try:
            return json.loads(payload)
        except Exception:
            continue

    # Strategy 2: Manual field extraction
    diagram_match = re.search(r'"diagram"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, re.DOTALL)
    summary_match = re.search(r'"summary"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', text, re.DOTALL)
    
    if diagram_match and summary_match:
        return {
            "diagram": diagram_match.group(1).replace('\\n', '\n').replace('\\"', '"'),
            "summary": summary_match.group(1).replace('\\n', '\n').replace('\\"', '"')
        }

    raise ValueError("No valid JSON found")


def _extract_functions_from_project(project_data: dict) -> list:
    """Extract functions/components with frontend support."""
    if "functions" in project_data and project_data["functions"]:
        return project_data["functions"]
    
    if "relationships" in project_data:
        func_names = set()
        for rel in project_data["relationships"]:
            rel_type = rel.get("type", "")
            if rel_type in ["calls", "invokes", "function_call", "uses", "renders"]:
                source = rel.get("source", "")
                target = rel.get("target", "")
                if source:
                    func_names.add(source)
                if target:
                    func_names.add(target)
        
        if func_names:
            return [{"name": name, "file": ""} for name in sorted(func_names)]
    
    files = project_data.get("files", [])
    if files:
        return [
            {
                "name": f.get("path", "file").split("/")[-1],
                "file": f.get("path", ""),
                "is_file_fallback": True
            }
            for f in files
        ]
    
    return []


def _detect_frontend_features(project_data: dict) -> dict:
    """Detect React/Vue specific features."""
    metadata = project_data.get("metadata", {})
    project_type = metadata.get("project_type", "")
    
    is_react = project_type == "React"
    is_vue = project_type == "Vue"
    is_frontend = is_react or is_vue or project_type in ["JavaScript/TypeScript", "Frontend"]
    
    # Count components
    component_count = sum(
        1 for f in project_data.get("functions", [])
        if f.get("type") == "component"
    )
    
    return {
        "is_frontend": is_frontend,
        "is_react": is_react,
        "is_vue": is_vue,
        "project_type": project_type,
        "has_components": component_count > 0,
        "component_count": component_count,
    }


def _format_prompt(project_data: dict) -> str:
    """
    Compact, strict prompt optimized for small models (Qwen 3B, Phi3 Mini).
    Token budget: ~800-1000 tokens max
    """
    functions = _extract_functions_from_project(project_data)[:12]  # Limit to 12
    relationships = project_data.get("relationships", [])[:15]  # Limit to 15
    frontend_features = _detect_frontend_features(project_data)
    
    # Build node definitions
    node_lines = []
    node_ids = {}
    for i, func in enumerate(functions):
        name = func.get("name", f"node{i}")
        node_id = sanitize_id(name)
        node_ids[name] = node_id
        label = name[:30]  # Truncate long names
        node_lines.append(f'{node_id}["{label}"]')
    
    # Build edge definitions
    edge_lines = []
    for rel in relationships:
        source = rel.get("source", "")
        target = rel.get("target", "")
        if source in node_ids and target in node_ids:
            edge_lines.append(f"{node_ids[source]} --> {node_ids[target]}")
    
    # Create minimal examples
    nodes_example = "\n".join(node_lines[:6]) if node_lines else "A[Component]\nB[Helper]"
    edges_example = "\n".join(edge_lines[:5]) if edge_lines else "A --> B"
    
    # Project context
    if frontend_features["is_react"]:
        context = "React components"
    elif frontend_features["is_vue"]:
        context = "Vue components"
    elif frontend_features["is_frontend"]:
        context = "Frontend modules"
    else:
        context = "Functions"
    
    prompt = f"""You must output ONLY valid JSON. No extra text.

Required format:
{{"diagram": "flowchart TD\\n...", "summary": "..."}}

Project: {context} ({len(functions)} items, {len(relationships)} connections)

Example nodes to use:
{nodes_example}

Example edges to use:
{edges_example}

Rules:
1. Start with: flowchart TD
2. Use 5-10 nodes from examples
3. Use 3-8 edges from examples
4. Summary: 3-5 sentences
5. Output ONLY JSON

Example output:
{{"diagram": "flowchart TD\\n  App[\\"App\\"]\\n  Main[\\"Main\\"]\\n  App --> Main", "summary": "Simple {context.lower()} architecture with main entry point."}}

Generate JSON now:"""

    return prompt


def _create_basic_diagram(project_data: dict) -> str:
    """Create a context-aware fallback diagram."""
    functions = _extract_functions_from_project(project_data)[:10]
    relationships = project_data.get("relationships", [])[:20]
    frontend_features = _detect_frontend_features(project_data)

    lines = ["flowchart TD"]
    nodes: Dict[str, str] = {}

    # Add nodes
    if frontend_features["is_frontend"]:
        # Separate components and functions
        components = [f for f in functions if f.get("type") == "component"]
        functions_only = [f for f in functions if f.get("type") != "component"]
        
        for comp in components[:8]:
            comp_name = comp.get("name", "")
            if not comp_name:
                continue
            
            node_id = sanitize_id(comp_name)
            node_label = sanitize_label(comp_name)[:40]
            
            if node_id in nodes:
                continue
            
            nodes[node_id] = node_label
            lines.append(f'  {node_id}["{node_label}"]')
        
        for func in functions_only[:4]:
            func_name = func.get("name", "")
            if not func_name:
                continue
            
            node_id = sanitize_id(func_name)
            node_label = sanitize_label(func_name)[:40]
            
            if node_id in nodes:
                continue
            
            nodes[node_id] = node_label
            lines.append(f'  {node_id}["{node_label}"]')
    else:
        for func in functions:
            func_name = func.get("name", "")
            if not func_name:
                continue
            
            node_id = sanitize_id(func_name)
            node_label = sanitize_label(func_name)[:40]
            
            if node_id in nodes:
                continue
            
            nodes[node_id] = node_label
            lines.append(f'  {node_id}["{node_label}"]')

    # Add relationships
    for relation in relationships[:15]:
        source = sanitize_id(relation.get("source", ""))
        target = sanitize_id(relation.get("target", ""))
        
        if source in nodes and target in nodes:
            lines.append(f"  {source} --> {target}")

    # Fallback if empty
    if len(lines) == 1:
        if frontend_features["is_react"]:
            lines.extend([
                '  App["App"]',
                '  Page["Page"]',
                '  UI["UI"]',
                "  App --> Page",
                "  Page --> UI",
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


def _create_basic_summary(project_data: dict) -> str:
    """Create a context-aware fallback summary."""
    functions = _extract_functions_from_project(project_data)
    relationships = project_data.get("relationships", [])
    frontend_features = _detect_frontend_features(project_data)

    func_count = len(functions)
    relation_count = len(relationships)
    project_type = frontend_features["project_type"]

    if frontend_features["is_frontend"]:
        comp_count = frontend_features["component_count"]
        if comp_count > 0:
            return f"This {project_type} project has {comp_count} components with {relation_count} connections. The architecture shows component hierarchy and data flow. Review the diagram for detailed structure."
        else:
            return f"This {project_type} project has {func_count} modules with {relation_count} connections. The diagram shows the module relationships and execution flow."
    else:
        return f"This {project_type} project contains {func_count} functions with {relation_count} execution paths. The diagram illustrates the call flow and dependencies."


def _fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _create_basic_diagram(project_data), _create_basic_summary(project_data)


def _validate_diagram(diagram: str) -> bool:
    """Quick validation of diagram structure"""
    if not diagram.strip().startswith("flowchart"):
        return False
    
    lines = diagram.strip().split('\n')
    if len(lines) < 3:
        return False
    
    # Count nodes and edges
    has_nodes = any('[' in line and ']' in line for line in lines[1:])
    has_edges = any('-->' in line for line in lines)
    
    return has_nodes and has_edges


def generate_diagram_and_summary(
    project_data: dict,
    ollama_client: OllamaClient | None = None,
) -> Tuple[str, str]:
    client = _select_client(ollama_client)
    prompt = _format_prompt(project_data)
    
    # Token warning
    if len(prompt) > 4000:
        print(f"⚠ Warning: Prompt length {len(prompt)} chars (~{len(prompt)//4} tokens) may be too long for small models")

    response = client.generate(prompt)
    payload = _safe_json_extract(response)

    diagram = payload.get("diagram", "").strip()
    summary = payload.get("summary", "").strip()
    
    # Validate diagram
    if not _validate_diagram(diagram):
        print("⚠ Diagram validation failed, using fallback")
        raise ValueError("Invalid diagram structure")

    return diagram, summary


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

    # Final safety check
    if not diagram or not summary or not _validate_diagram(diagram):
        print("⚠ Output validation failed, using fallback")
        diagram, summary = _fallback_generation(project_data)

    return diagram, summary


def fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _fallback_generation(project_data)

