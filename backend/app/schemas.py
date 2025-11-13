from __future__ import annotations

from pydantic import BaseModel, Field


class AnalysisResponse(BaseModel):
    diagram: str = Field(..., description="Mermaid diagram code")
    summary: str = Field(..., description="4–8 line textual summary")


__all__ = ["AnalysisResponse"]


