from __future__ import annotations

import re
from typing import Dict, Tuple


_FALLBACK_DIAGRAM = (
    "flowchart TD\n"
    "  A[Analysis Complete]\n"
    "  B[Review Summary]\n"
    "  A --> B"
)


def sanitize_id(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text or "node"


def sanitize_label(text: str) -> str:
    label = (text or "").strip()
    label = re.sub(r"\s+", " ", label)
    label = label.replace('"', "'")
    return label or "node"


def is_mermaid_valid(diagram: str) -> bool:
    if not isinstance(diagram, str):
        return False
    if not diagram.startswith("flowchart TD"):
        return False
    if "-->" not in diagram:
        return False
    return True


def _normalize_text(diagram: str) -> str:
    cleaned = diagram or ""
    cleaned = cleaned.replace("=>", "-->").replace("->", "-->")
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"[`\*\|]", " ", cleaned)
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    return cleaned


def fix_mermaid(diagram: str) -> str:
    if not isinstance(diagram, str) or not diagram.strip():
        return _FALLBACK_DIAGRAM

    diagram = _normalize_text(diagram)

    node_labels: Dict[str, str] = {}
    edges: list[Tuple[str, str]] = []

    arrow_pattern = re.compile(r"([A-Za-z0-9_\-\.]+)\s*[-=]*>\s*([A-Za-z0-9_\-\.]+)")
    node_pattern = re.compile(
        r"^\s*([A-Za-z0-9_\-\.]+)\s*(?:\[(.+?)\]|\((.+?)\)|\{(.+?)\})"
    )

    for raw_line in diagram.split("\n"):
        line = raw_line.strip()
        if not line or line.lower().startswith("flowchart"):
            continue

        line = re.sub(r"\s+-\s+", "-->", line)
        line = re.sub(r"\s*--?\s*>\s*", "-->", line)

        edge_match = arrow_pattern.search(line)
        if edge_match:
            source_raw, target_raw = edge_match.groups()
            source = sanitize_id(source_raw)
            target = sanitize_id(target_raw)
            if source and target:
                edges.append((source, target))
            continue

        node_match = node_pattern.match(line)
        if node_match:
            node_raw = node_match.group(1)
            label_raw = next(
                (group for group in node_match.groups()[1:] if group is not None),
                node_raw,
            )
            node_id = sanitize_id(node_raw)
            node_labels.setdefault(node_id, sanitize_label(label_raw))
            continue

        maybe_node = re.match(r"^\s*([A-Za-z0-9_\-\.]+)\s*$", line)
        if maybe_node:
            node_id = sanitize_id(maybe_node.group(1))
            node_labels.setdefault(node_id, sanitize_label(node_id))

    for source, target in edges:
        node_labels.setdefault(source, sanitize_label(source))
        node_labels.setdefault(target, sanitize_label(target))

    if not node_labels:
        node_labels["project"] = "Project"

    node_ids = list(node_labels.keys())
    if not edges and len(node_ids) >= 2:
        edges.append((node_ids[0], node_ids[1]))
    elif not edges:
        edges.append(("project", "project"))

    lines = ["flowchart TD"]
    for node_id, label in node_labels.items():
        lines.append(f'  {node_id}["{label}"]')

    for source, target in edges:
        if source == target and source == "project" and source not in node_labels:
            continue
        lines.append(f"  {source} --> {target}")

    final_diagram = "\n".join(lines)

    if not is_mermaid_valid(final_diagram):
        return _FALLBACK_DIAGRAM

    return final_diagram


def ensure_valid(diagram: str) -> Tuple[str, Dict[str, bool]]:
    if is_mermaid_valid(diagram):
        return diagram, {"fixed": False, "valid": True}

    repaired = fix_mermaid(diagram)
    if is_mermaid_valid(repaired):
        return repaired, {"fixed": True, "valid": True}

    return _FALLBACK_DIAGRAM, {"fixed": True, "valid": False}

