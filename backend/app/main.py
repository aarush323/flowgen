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
print("Loaded key:", API_KEY is not None)

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
# PROMPT CREATOR
# =====================================================================================
def build_prompt(project_data: dict[str, Any]) -> str:
    minimal = {
        "files": [
            {
                "id": re.sub(r"[^a-zA-Z0-9_]", "_", f["path"]),
                "label": f["path"].split("/")[-1],
            }
            for f in project_data.get("files", [])[:120]
        ],
        "relationships": [
            {
                "source": re.sub(r"[^a-zA-Z0-9_]", "_", r["source"]),
                "target": re.sub(r"[^a-zA-Z0-9_]", "_", r["target"]),
                "type": r["type"],
            }
            for r in project_data.get("relationships", [])
        ],
    }

    structure_json = json.dumps(minimal, indent=2)

    return textwrap.dedent(f"""
You generate ONLY JSON. No text before or after.

FORMAT:
{{
  "diagram": "flowchart TD\\n<NODES_AND_EDGES>",
  "summary": "<4_to_8_sentences>"
}}

DIAGRAM RULES:
- Must start with: flowchart TD
- One node per file: id["label"]
- Arrows: source --> target
- Use ONLY the IDs given
- Minimum 3 nodes, 2 arrows
- No markdown

PROJECT DATA:
{structure_json}
""").strip()
