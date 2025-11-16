# app/main.py

from __future__ import annotations
from dotenv import load_dotenv

import os
import json
import textwrap
import zipfile
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .parser import ProjectParser
from .diagram_fix import fix_mermaid, is_mermaid_valid
from .schemas import AnalysisResponse
from .graph_cleaner import ensure_valid
from .llm_client import OpenRouterClient

# Load environment variables
load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")
print("API Key loaded successfully." if API_KEY else "API Key NOT found.")

client = OpenRouterClient()
parser = ProjectParser()

app = FastAPI(title="AI Code Architecture & Flow Diagram Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health", response_class=JSONResponse)
async def health() -> dict[str, str]:
    return {"status": "ok"}


# =====================================================================================
# UPLOAD ROUTE
# =====================================================================================
@app.post("/upload", response_model=AnalysisResponse)
async def upload_project(file: UploadFile = File(...)) -> AnalysisResponse:
    print("UPLOAD ENDPOINT HIT:", file.filename)

    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are supported.")

    base_dir = Path(__file__).resolve().parent / "projects"
    base_dir.mkdir(parents=True, exist_ok=True)

    project_dir = base_dir / (
        f"proj_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
    )
    project_dir.mkdir(parents=True, exist_ok=True)

    zip_path = project_dir / file.filename
    content = await file.read()
    zip_path.write_bytes(content)

    extracted_dir = project_dir / "extracted"
    extracted_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extracted_dir)

    project_data = parser.parse_zip(zip_path)

    # ---- LLM CALL ----
    prompt = build_prompt(project_data)
    raw = client.generate(prompt)

    # --- DEBUG LINE ADDED ---
    # This will print the exact raw response from the LLM to your terminal.
    print(f"DEBUG: Raw LLM output:\n---\n{raw}\n---")

    try:
        payload = json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM returned invalid JSON: {e}")

    diagram = payload.get("diagram", "")
    summary = payload.get("summary", "")

    # ---- DIAGRAM FIXING ----
    if not is_mermaid_valid(diagram):
        diagram, metadata = ensure_valid(diagram)
        if not metadata.get("valid"):
            diagram = fix_mermaid(diagram)
        if not is_mermaid_valid(diagram):
            diagram = "flowchart TD\n  A[Analysis Complete]\n  B[See Summary]\n  A --> B"

    if not summary or len(summary) < 20:
        summary = "The project structure has been analyzed. Review the flowchart for details."

    return AnalysisResponse(diagram=diagram, summary=summary)


# =====================================================================================
# V2.2 - STRICTER, DATA-DRIVEN PROMPT CREATOR (Anti-Repetition)
# =====================================================================================
def build_prompt(project_data: dict[str, Any]) -> str:
    """
    Creates a highly specific prompt that forces the LLM to only use connected components
    and avoid drawing duplicate relationships.
    """

    # --- 1. Extract all unique components that are actually connected ---
    connected_components = set()
    for rel in project_data.get("relationships", [])[:50]:
        connected_components.add(rel.get("source", "Unknown"))
        connected_components.add(rel.get("target", "Unknown"))

    # --- 2. Prepare a summary of ONLY the connected functions ---
    functions_summary = []
    for func in project_data.get("functions", []):
        # Only include functions that are part of the connected flow
        if func.get("name") in connected_components:
            doc = func.get("doc", "No description available.")
            if len(doc) > 100:
                doc = doc[:97] + "..."
            functions_summary.append(
                f"- Function: `{func['name']}` (in `{func['file']}`)\n  Purpose: {doc}"
            )

    # --- 3. Prepare a structured list of relationships ---
    relationships_summary = []
    for rel in project_data.get("relationships", [])[:50]:
        source = rel.get("source", "Unknown")
        target = rel.get("target", "Unknown")
        rel_type = rel.get("type", "unknown")
        relationships_summary.append(f"- `{source}` --[{rel_type}]--> `{target}`")

    # --- 4. Construct the final, strict prompt ---
    prompt = f"""
You are an expert software architect visualizing a codebase's execution flow.
Your task is to create a precise Mermaid.js flowchart based *strictly* on the provided components and their relationships.

**CONNECTED COMPONENTS (These are the ONLY items you should create nodes for):**
{chr(10).join(list(connected_components))}

**COMPONENT DETAILS (For context and labeling):**
{chr(10).join(functions_summary)}

**RELATIONSHIPS (The exact connections to draw):**
{chr(10).join(relationships_summary)}

**CRITICAL INSTRUCTIONS FOR THE FLOWCHART:**
1.  **Output ONLY a JSON object** with two keys: "diagram" and "summary".
2.  **Node Creation:** You MUST ONLY create nodes for items listed under "CONNECTED COMPONENTS". Do NOT create any other nodes.
3.  **Diagram Content:**
    - The "diagram" value must be a valid Mermaid.js flowchart string starting with `flowchart TD`.
    - Use rectangle nodes for functions: `function_name["Function Name"]`.
    - For each UNIQUE relationship listed under "RELATIONSHIPS", draw EXACTLY ONE arrow. Do not draw multiple arrows between the same two nodes.
    - Label arrows with the interaction type (e.g., `-- calls -->`).
4.  **Summary Content:**
    - The "summary" value must be a 4-8 sentence explanation of the project's architecture, focusing on the flow between the connected components.

**OUTPUT FORMAT (strictly follow this):**
{{
  "diagram": "flowchart TD\\n  A[Main Entry] --> B[Core Logic]\\n  B --> C[Database]",
  "summary": "This project is structured with a main entry point that calls into core logic modules. The core logic interacts with a database layer for data persistence."
}}

Generate the diagram and summary based on the data and rules above.
"""
    return textwrap.dedent(prompt).strip()