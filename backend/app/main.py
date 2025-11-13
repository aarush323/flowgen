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
from .llm_steps import process_with_steps, fallback_generation
from .graph_cleaner import ensure_valid


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

        file_count = len(project_data.get("files", []))
        relationship_count = len(project_data.get("relationships", []))
        print("DEBUG 7A: File count detected:", file_count)
        print("DEBUG 7B: Relationship count detected:", relationship_count)

        try:
            print("DEBUG 8: Starting process_with_steps() pipeline...")
            diagram, summary = process_with_steps(project_data, ollama_client)
            print("DEBUG 9: Diagram length before validation =", len(diagram))
            print("DEBUG 10: Summary length before validation =", len(summary))
        except Exception as pipeline_exc:
            print("DEBUG LLM PIPELINE ERROR:", repr(pipeline_exc))
            diagram, summary = fallback_generation(project_data)
            print("DEBUG 8B: Fallback generation used after pipeline error.")

        validation_metadata = {"fixed": False, "valid": is_mermaid_valid(diagram)}
        try:
            if not validation_metadata["valid"]:
                print("⚠ Diagram invalid → applying fix_mermaid()")
                diagram, validation_metadata = ensure_valid(diagram)
                print("DEBUG 11: ensure_valid metadata:", validation_metadata)
                if not validation_metadata.get("valid"):
                    print("DEBUG 11B: ensure_valid failed, applying hard fallback diagram.")
                    diagram = "flowchart TD\n  A[Analysis Complete]\n  B[See Summary]\n  A --> B"
            else:
                print("✔ Diagram already valid, skipping fix.")
        except Exception as ensure_exc:
            print("DEBUG ERROR ensure_valid:", repr(ensure_exc))
            diagram = fix_mermaid(diagram)
            validation_metadata = {"fixed": True, "valid": is_mermaid_valid(diagram)}
            if not validation_metadata.get("valid"):
                print("DEBUG 11C: fix_mermaid fallback still invalid, forcing hard fallback diagram.")
                diagram = "flowchart TD\n  A[Analysis Complete]\n  B[See Summary]\n  A --> B"

        if not summary or len(summary) < 20:
            summary = (
                f"This project contains {file_count} files and {relationship_count} relationships. "
                "Review the generated flowchart for architecture context."
            )
            print("DEBUG 12: Summary fallback applied.")
        else:
            print("DEBUG 12: Summary passed minimum length check.")

        print("DEBUG 13: Validation complete. Final diagram length:", len(diagram))
        print("DEBUG 14: Final summary length:", len(summary))


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
