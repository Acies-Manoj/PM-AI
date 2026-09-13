from typing import Literal

from fastapi import APIRouter, HTTPException, Response

from app.schemas import ReportOutput
from app.services import report_generator
from app.services.analysis_store import store as analysis_store

router = APIRouter(prefix="/api/report", tags=["report"])


@router.post("/generate", response_model=ReportOutput)
def generate_report(analysis_id: str, fmt: Literal["html", "markdown"] = "html") -> ReportOutput:
    a = analysis_store.get(analysis_id)
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return report_generator.generate_report(
        analysis_id=a.analysis_id,
        session_id=a.session_id,
        brief=a.brief,
        steps=a.steps,
        validated_results=a.validated_results,
        fmt=fmt,
    )


@router.get("/download")
def download_report(analysis_id: str, fmt: str = "html"):
    a = analysis_store.get(analysis_id)
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    output = report_generator.generate_report(
        analysis_id=a.analysis_id,
        session_id=a.session_id,
        brief=a.brief,
        steps=a.steps,
        validated_results=a.validated_results,
        fmt=fmt,
    )
    content_type = "text/html" if fmt == "html" else "text/markdown"
    ext = "html" if fmt == "html" else "md"
    return Response(
        content=output.content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="cold_chain_report.{ext}"'},
    )
