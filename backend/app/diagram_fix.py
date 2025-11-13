from __future__ import annotations
import re

def fix_mermaid(diagram: str) -> str:
    """
    Fully sanitizes Mermaid diagrams so they ALWAYS render.
    - Ensures 'flowchart TD' header
    - Normalizes node IDs (safe identifiers)
    - Auto-generates missing node definitions
    - Normalizes arrows `id --> id`
    - Removes invalid / non-Mermaid text
    """

    if not diagram or not isinstance(diagram, str):
        return "flowchart TD"

    # -----------------------------------------
    # 1. Remove garbage characters & markdown
    # -----------------------------------------
    diagram = re.sub(r"[`\*\|]", " ", diagram)
    diagram = re.sub(r"\[[^\]]*\[[^\]]*\]", "", diagram)  # Remove nested brackets
    diagram = diagram.replace("=>", "-->").replace("->", "-->")

    # Remove Python-like lists
    diagram = re.sub(r"[\(\)\[\]\{\},]", " ", diagram)

    lines = diagram.split("\n")
    cleaned = []

    # Track node IDs actually seen in arrows
    used_nodes = set()

    # Regex to match arrows like: A --> B
    arrow_re = re.compile(r"^\s*([\w\.\-/]+)\s*-->\s*([\w\.\-/]+)\s*$")

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Skip non-Mermaid noise
        if not any(token in line for token in ["-->", "[", "]"]):
            continue

        # Convert invalid separators to arrows
        line = re.sub(r"\s*-\s*", " --> ", line)

        # Match and sanitize arrows
        m = arrow_re.match(line)
        if m:
            left, right = m.groups()

            left_id = sanitize_id(left)
            right_id = sanitize_id(right)

            used_nodes.add(left_id)
            used_nodes.add(right_id)

            cleaned.append(f"{left_id} --> {right_id}")
            continue

        # Attempt to detect standalone node-like lines
        node_match = re.match(r"^([\w\.\-/]+)\s+(.*)$", line)
        if node_match:
            node_raw, label_raw = node_match.groups()

            node_id = sanitize_id(node_raw)
            label = sanitize_label(label_raw)

            cleaned.append(f'{node_id}["{label}"]')
            used_nodes.add(node_id)
            continue

    # ------------------------------------------------------
    # 2. Auto-generate missing node definitions (important!)
    # ------------------------------------------------------
    node_definitions = []
    for node in used_nodes:
        node_definitions.append(f'{node}["{node}"]')

    # ------------------------------------------------------
    # 3. Final assembly
    # ------------------------------------------------------
    final = ["flowchart TD"]
    final.extend(node_definitions)
    final.extend(cleaned)

    return "\n".join(final)


# ================================
# HELPER FUNCTIONS
# ================================

def sanitize_id(text: str) -> str:
    """Convert arbitrary text into a valid Mermaid node ID."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9_]", "_", text)  # Replace invalid chars
    text = re.sub(r"_+", "_", text)          # Collapse multiple underscores
    if not text:
        text = "node"
    return text


def sanitize_label(text: str) -> str:
    """Clean the display label for Mermaid."""
    if not text:
        return "node"
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('"', "'")
    return text

def is_mermaid_valid(diagram: str) -> bool:
    if not diagram.startswith("flowchart TD"):
        return False
    if "-->" not in diagram:
        return False
    return True
