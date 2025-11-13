from __future__ import annotations

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

from .ollama import OllamaClient
from .parser import ProjectParser
from .diagram_fix import fix_mermaid,is_mermaid_valid
from .schemas import AnalysisResponse


app = FastAPI(title="AI Code Architecture & Flow Diagram Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

parser = ProjectParser()
ollama_client = OllamaClient()


@app.get("/health", response_class=JSONResponse)
async def health() -> dict[str, str]:
    return {"status": "ok"}


# =====================================================================================
# 🔥 FINAL /upload ROUTE — PERMANENT STORAGE + ROBUST LLM PARSING
# =====================================================================================
@app.post("/upload", response_model=AnalysisResponse)
async def upload_project(file: UploadFile = File(...)) -> AnalysisResponse:
    print("UPLOAD ENDPOINT HIT")
    print("REQUEST RECEIVED:", file.filename if file else "NO FILE")

    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are supported.")

    # Base storage folder
    base_dir = Path(__file__).resolve().parent / "projects"
    base_dir.mkdir(parents=True, exist_ok=True)

    # Create a unique folder
    project_dir = base_dir / (
        f"myproject_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
    )
    project_dir.mkdir(parents=True, exist_ok=True)

    # Save ZIP permanently
    zip_path = project_dir / file.filename
    content = await file.read()
    zip_path.write_bytes(content)
    print(f"Successfully received file: {file.filename}")
    print("DEBUG 5: ZIP saved OK:", zip_path)

    # Extract ZIP permanently
    extracted_dir = project_dir / "extracted"
    extracted_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extracted_dir)

    print("DEBUG 6: Starting parser.parse_zip()")

    try:
        project_data = parser.parse_zip(zip_path)
        print("DEBUG 7: Parser output keys:", list(project_data.keys()))

        print("DEBUG 8: Building LLM prompt...")
        prompt = build_prompt(project_data)
        print("DEBUG 9: Prompt length =", len(prompt))

        print("DEBUG 10: Calling Ollama model:", ollama_client.model)
        ollama_output = ollama_client.generate(prompt)
        print("DEBUG 11: Ollama returned output length:", len(ollama_output))

        print("DEBUG 12: Parsing Ollama JSON...")
        diagram, summary = parse_ollama_output(ollama_output)
        print("DEBUG 13: JSON parse successful.")

        # 🔥 FIX MERMAID BEFORE RETURN
        # Only repair if the model produced junk
        if not is_mermaid_valid(diagram):
            print("⚠ Diagram invalid → applying fix_mermaid()")
            diagram = fix_mermaid(diagram)
        else:
            print("✔ Diagram already valid, skipping fix.")


    except HTTPException as exc:
        print("DEBUG ERROR:", repr(exc))
        raise
    except Exception as exc:
        print("DEBUG ERROR:", repr(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return AnalysisResponse(diagram=diagram, summary=summary)


# =====================================================================================
# 🔥 ROBUST JSON-ONLY PROMPT
# =====================================================================================
def build_prompt(project_data: dict[str, Any]) -> str:
    """
    Compact but strict prompt that guarantees:
    - Model ALWAYS outputs nodes + arrows
    - JSON ONLY
    - Works reliably with small local models (Qwen 3B, Phi3 Mini)
    """

    # Sanitize and compress structure
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

OUTPUT FORMAT (MANDATORY):
{{
  "diagram": "flowchart TD\\n<NODES_AND_ARROWS>",
  "summary": "<4_to_8_sentences>"
}}

DIAGRAM RULES (YOU MUST FOLLOW ALL):
- diagram MUST START with: flowchart TD
- One node PER file:  id["label"]
- For each relationship:
    - source --> target
- ONLY use the IDs provided in the structure
- AT LEAST 3 nodes MUST be present
- AT LEAST 2 arrows MUST be present
- DO NOT invent new IDs
- NO markdown, NO comments, NO prose

EXAMPLE OF CORRECT STYLE:
flowchart TD
  a_py["a.py"]
  b_js["b.js"]
  a_py --> b_js

SUMMARY RULES:
- 4–8 short sentences
- No bullets, no lists

PROJECT STRUCTURE (USE THESE IDS AND LABELS):
{structure_json}
""").strip()




# =====================================================================================
# 🔥 BULLETPROOF JSON PARSER
# =====================================================================================
def parse_ollama_output(output: str) -> tuple[str, str]:
    # Remove illegal control characters
    sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", output)

    # Extract JSON from messy output
    match = re.search(r"\{.*\}", sanitized, flags=re.DOTALL)
    if not match:
        raise RuntimeError("Could not extract JSON from model output.")

    json_text = match.group(0)

    try:
        data = json.loads(json_text)
    except Exception as exc:
        raise RuntimeError(f"Model returned invalid JSON: {exc}")

    if "diagram" not in data or "summary" not in data:
        raise RuntimeError("Model JSON missing required keys 'diagram' or 'summary'.")

    return data["diagram"].strip(), data["summary"].strip()
