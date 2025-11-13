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
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)

    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
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

    raise ValueError("No valid JSON found")


def _format_prompt(project_data: dict) -> str:
    files = project_data.get("files", [])[:50]
    relationships = project_data.get("relationships", [])[:100]

    file_lines = "\n".join(
        f"- {f.get('path', 'unknown')}"
        for f in files
    ) or "- (no files detected)"

    relationship_lines = "\n".join(
        f"- {r.get('source', 'unknown')} \u2192 {r.get('target', 'unknown')} ({r.get('type', 'relation')})"
        for r in relationships
    ) or "- (no relationships detected)"

    prompt = f"""
You are analyzing a code project. Generate a Mermaid flowchart and summary.

FILES:
{file_lines}

KEY RELATIONSHIPS:
{relationship_lines}

Your task:
1. Create a flowchart showing the main components and how they connect
2. Write a brief summary (4-6 sentences) explaining the architecture

IMPORTANT OUTPUT FORMAT:
You MUST respond with valid JSON in this exact format:

{{
  "diagram": "flowchart TD\\nA[Component A]\\nB[Component B]\\nA --> B",
  "summary": "This project does X. The main component is Y..."
}}

Rules for the diagram:
- Start with: flowchart TD
- Each component: ID["Label"]
- Connections: ID1 --> ID2
- Use simple alphanumeric IDs (no spaces or special chars)
- Include at least 3-5 main components

Rules for summary:
- 4-6 clear sentences
- Explain what the project does
- Mention key components
- No bullet points
    """.strip()

    return prompt


def _create_basic_diagram(project_data: dict) -> str:
    files = project_data.get("files", [])[:10]
    relationships = project_data.get("relationships", [])[:20]

    lines = ["flowchart TD"]
    nodes: Dict[str, str] = {}

    for file_info in files:
        raw_path = file_info.get("path", "")
        node_id = sanitize_id(raw_path or file_info.get("id", "file"))
        label = file_info.get("path", "") or file_info.get("label", node_id)
        label = label.split("/")[-1] or node_id
        node_label = sanitize_label(label)
        if node_id in nodes:
            continue
        nodes[node_id] = node_label
        lines.append(f'  {node_id}["{node_label}"]')

    for relation in relationships:
        source = sanitize_id(relation.get("source", ""))
        target = sanitize_id(relation.get("target", ""))
        if source in nodes and target in nodes:
            lines.append(f"  {source} --> {target}")

    if len(lines) == 1:
        lines.extend(
            [
                '  project["Project"]',
                '  data["Data Flow"]',
                "  project --> data",
            ]
        )

    return "\n".join(lines)


def _create_basic_summary(project_data: dict) -> str:
    files = project_data.get("files", [])
    relationships = project_data.get("relationships", [])
    metadata = project_data.get("metadata", {})

    file_count = len(files)
    relation_count = len(relationships)
    tech_stack = metadata.get("tech_stack") or metadata.get("languages") or []

    parts = [
        f"This project contains {file_count} tracked files" if file_count else "This project contains a small set of files",
        f"It models {relation_count} relationships between components" if relation_count else "Component links are minimal in the current snapshot",
        f"The primary technologies include {', '.join(tech_stack)}" if tech_stack else "The code appears to rely on standard tooling",
        "Use the generated flowchart to understand the high level execution path",
    ]

    return ". ".join(parts) + "."


def _fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _create_basic_diagram(project_data), _create_basic_summary(project_data)


def generate_diagram_and_summary(
    project_data: dict,
    ollama_client: OllamaClient | None = None,
) -> Tuple[str, str]:
    client = _select_client(ollama_client)
    prompt = _format_prompt(project_data)

    response = client.generate(prompt)
    payload = _safe_json_extract(response)

    diagram = payload.get("diagram", "")
    summary = payload.get("summary", "")

    return diagram, summary


def process_with_steps(
    project_data: dict,
    ollama_client: OllamaClient | None = None,
) -> Tuple[str, str]:
    try:
        diagram, summary = generate_diagram_and_summary(project_data, ollama_client)
    except Exception as exc:
        print("DEBUG LLM ERROR:", repr(exc))
        diagram, summary = _fallback_generation(project_data)
        return diagram, summary

    if not diagram or not summary:
        diagram, summary = _fallback_generation(project_data)

    return diagram, summary


def fallback_generation(project_data: dict) -> Tuple[str, str]:
    return _fallback_generation(project_data)

