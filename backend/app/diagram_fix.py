# app/diagram_fix.py

from __future__ import annotations

import re
from typing import Dict, Tuple, List


# -------------------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------------------

_FALLBACK_DIAGRAM = (
    "flowchart TD\n"
    "  A[Analysis Complete]\n"
    "  B[Review Summary]\n"
    "  A --> B"
)


# -------------------------------------------------------------------------------------
# Sanitizers
# -------------------------------------------------------------------------------------

def sanitize_id(text: str) -> str:
    """Convert arbitrary text → safe Mermaid node id."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]", "_", text)
    text = re.sub(r"_+", "_", text)
    return text or "node"


def sanitize_label(text: str) -> str:
    """Clean human-readable label."""
    label = (text or "").strip()
    label = re.sub(r"\s+", " ", label)
    label = label.replace('"', "'")
    return label or "node"


# -------------------------------------------------------------------------------------
# Basic validity check
# -------------------------------------------------------------------------------------

def is_mermaid_valid(diagram: str) -> bool:
    """Very lightweight sanity check to prevent broken Mermaid output."""
    # --- DEBUG LINE ADDED ---
    print("🔍 DIAGRAM_FIX: Running is_mermaid_valid()...")
    
    if not isinstance(diagram, str):
        print("❌ DIAGRAM_FIX: Invalid type. Not a string.")
        return False
    if not diagram.startswith("flowchart TD"):
        print("❌ DIAGRAM_FIX: Invalid format. Does not start with 'flowchart TD'.")
        return False
    if "-->" not in diagram:
        print("❌ DIAGRAM_FIX: Invalid format. No arrows ('-->') found.")
        return False
    
    # --- DEBUG LINE ADDED ---
    print("✅ DIAGRAM_FIX: is_mermaid_valid() returned True.")
    return True


# -------------------------------------------------------------------------------------
# Internal cleaning helpers
# -------------------------------------------------------------------------------------

def _normalize_text(diagram: str) -> str:
    """Remove markdown trash + unify arrows."""
    cleaned = diagram or ""
    cleaned = cleaned.replace("=>", "-->").replace("->", "-->")
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"[`\*\|]", " ", cleaned)
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    return cleaned


# -------------------------------------------------------------------------------------
# Diagram repair engine
# -------------------------------------------------------------------------------------

def fix_mermaid(diagram: str) -> str:
    """
    Repair broken Mermaid diagrams:
      - extract nodes
      - extract edges
      - sanitize everything
      - rebuild from scratch
    """
    # --- DEBUG LINE ADDED ---
    print("🔧 DIAGRAM_FIX: Running fix_mermaid() to attempt a repair...")

    if not isinstance(diagram, str) or not diagram.strip():
        print("🔧 DIAGRAM_FIX: Input is empty or not a string. Returning fallback.")
        return _FALLBACK_DIAGRAM

    diagram = _normalize_text(diagram)

    node_labels: Dict[str, str] = {}
    edges: List[Tuple[str, str]] = []

    arrow_pattern = re.compile(r"([A-Za-z0-9_\-\.]+)\s*[-=]*>\s*([A-Za-z0-9_\-\.]+)")
    node_pattern = re.compile(
        r"^\s*([A-Za-z0-9_\-\.]+)\s*(?:\[(.+?)\]|\((.+?)\)|\{(.+?)\})"
    )

    for raw_line in diagram.split("\n"):
        line = raw_line.strip()
        if not line or line.lower().startswith("flowchart"):
            continue

        # Normalize arrows
        line = re.sub(r"\s+-\s+", "-->", line)
        line = re.sub(r"\s*--?\s*>\s*", "-->", line)

        # Try edge extraction
        edge_match = arrow_pattern.search(line)
        if edge_match:
            src_raw, dst_raw = edge_match.groups()
            src = sanitize_id(src_raw)
            dst = sanitize_id(dst_raw)
            if src and dst:
                edges.append((src, dst))
            continue

        # Try node extraction
        node_match = node_pattern.match(line)
        if node_match:
            raw_id = node_match.group(1)
            raw_label = next(
                (g for g in node_match.groups()[1:] if g is not None),
                raw_id,
            )
            node_id = sanitize_id(raw_id)
            node_labels.setdefault(node_id, sanitize_label(raw_label))
            continue

        # Bare node (rare case)
        bare = re.match(r"^\s*([A-Za-z0-9_\-\.]+)\s*$", line)
        if bare:
            node_id = sanitize_id(bare.group(1))
            node_labels.setdefault(node_id, sanitize_label(node_id))

    # Ensure nodes exist for edges
    for src, dst in edges:
        node_labels.setdefault(src, sanitize_label(src))
        node_labels.setdefault(dst, sanitize_label(dst))

    # Minimum fallback node(s)
    if not node_labels:
        node_labels["project"] = "Project"

    node_ids = list(node_labels.keys())

    # Ensure minimum 1 edge
    if not edges:
        if len(node_ids) >= 2:
            edges.append((node_ids[0], node_ids[1]))
        else:
            edges.append(("project", "project"))

    # ---------------------------------------------------------------------------------
    # Reconstruct diagram
    # ---------------------------------------------------------------------------------
    lines = ["flowchart TD"]

    for nid, label in node_labels.items():
        lines.append(f'  {nid}["{label}"]')

    for src, dst in edges:
        # Avoid infinite looping on the fallback placeholder
        if src == dst and src == "project" and "project" not in node_labels:
            continue
        lines.append(f"  {src} --> {dst}")

    final = "\n".join(lines)

    if is_mermaid_valid(final):
        print("✅ DIAGRAM_FIX: fix_mermaid() successfully repaired the diagram.")
    else:
        print("❌ DIAGRAM_FIX: fix_mermaid() failed to repair the diagram.")

    return final if is_mermaid_valid(final) else _FALLBACK_DIAGRAM


# -------------------------------------------------------------------------------------
# Full validation wrapper
# -------------------------------------------------------------------------------------

def ensure_valid(diagram: str) -> Tuple[str, Dict[str, bool]]:
    """
    Validate a diagram.
    If invalid:
        → repair it
        → if still invalid, fallback
    """
    # --- DEBUG LINE ADDED ---
    print("🛡️ DIAGRAM_FIX: Running ensure_valid() wrapper...")
    
    if is_mermaid_valid(diagram):
        print("✅ DIAGRAM_FIX: ensure_valid() found diagram is already valid. No fix needed.")
        return diagram, {"fixed": False, "valid": True}

    repaired = fix_mermaid(diagram)
    if is_mermaid_valid(repaired):
        print("✅ DIAGRAM_FIX: ensure_valid() successfully repaired the diagram.")
        return repaired, {"fixed": True, "valid": True}

    print("❌ DIAGRAM_FIX: ensure_valid() failed to repair. Returning final fallback.")
    return _FALLBACK_DIAGRAM, {"fixed": True, "valid": False}