from __future__ import annotations

"""
graph_cleaner.py
Central export point for all diagram-cleanup helpers:
- sanitize_id
- sanitize_label
- is_mermaid_valid
- fix_mermaid
- ensure_valid

This file doesn’t modify logic — it simply provides a clean,
stable interface for the rest of the backend.
"""

from typing import Dict, Tuple

from .diagram_fix import (
    ensure_valid,
    fix_mermaid,
    is_mermaid_valid,
    sanitize_id,
    sanitize_label,
)

__all__ = [
    "sanitize_id",
    "sanitize_label",
    "is_mermaid_valid",
    "fix_mermaid",
    "ensure_valid",
]


# Optional safety wrappers (useful when consuming untrusted text)
def clean_diagram(diagram: str) -> str:
    """
    Apply all cleaning passes to a Mermaid diagram:
    - sanitize IDs + labels
    - fix formatting
    - ensure minimal validity

    Always returns a valid-ish Mermaid string.
    """
    if not diagram or not isinstance(diagram, str):
        return "flowchart LR\n  empty[\"empty diagram\"]"

    fixed = fix_mermaid(diagram)
    valid = ensure_valid(fixed)
    return valid


def validate_or_default(diagram: str) -> str:
    """
    Check if a Mermaid diagram is valid.
    If invalid → return a simple default flow.
    """
    if is_mermaid_valid(diagram):
        return diagram

    return (
        "flowchart LR\n"
        "  start[\"Start\"] --> process[\"Process\"] --> end[\"End\"]"
    )
