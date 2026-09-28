"""Builds and streams a session's downloadable .pptx report -- entirely from
analyses already computed on the Analysis page (session.analysis_results)
and the last-computed overall analysis (session.overall_analysis). Never
triggers a new Analysis Agent run or narrative generation itself; a PM
computes those on the Analysis page first, and this router only reads
whatever is already there."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.dependencies import get_session_or_404 as _get_session_or_404
from app.schemas import LanguageOption, SupportedLanguagesResponse
from app.services.analysis import analysis_repository
from app.services.audit.audit_store import AuditSession
from app.services.report import report_generator, translation_service

router = APIRouter(prefix="/api/report", tags=["report"])


@router.get("/languages", response_model=SupportedLanguagesResponse)
def get_supported_languages() -> SupportedLanguagesResponse:
    """English plus whatever DeepL target languages translation_service
    currently lists -- see that module for what happens when no DeepL key
    is configured (every language still lists here, but the actual download
    silently falls back to English text)."""
    languages = [LanguageOption(code="en", name="English")] + [
        LanguageOption(code=code, name=name)
        for code, (name, _) in sorted(translation_service.SUPPORTED_LANGUAGES.items(), key=lambda kv: kv[1][0])
    ]
    return SupportedLanguagesResponse(languages=languages)


def _report_ready_entries(session: AuditSession, session_id: str, entry_ids: list[str] | None) -> list[dict]:
    """Definitions merged with their in-memory run result, limited to ones
    that actually finished successfully and (if entry_ids was given) were
    chosen for inclusion."""
    definitions = analysis_repository.get_repository(session_id)
    ready = []
    for definition in definitions:
        if entry_ids is not None and definition["id"] not in entry_ids:
            continue
        result = session.analysis_results.get(definition["id"])
        if result and result.run_status == "done":
            merged = dict(definition)
            merged.update(result.model_dump())
            ready.append(merged)
    return ready


@router.get("/{session_id}/download")
def download_report(session_id: str, entry_id: list[str] | None = Query(default=None), language: str = Query(default="en")):
    session = _get_session_or_404(session_id)
    entries = _report_ready_entries(session, session_id, entry_id)
    if not entries:
        raise HTTPException(
            status_code=422,
            detail="No completed analyses to include in the report -- run some on the Analysis page first.",
        )
    if language != "en" and language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"'{language}' isn't a supported report language.")

    pptx_bytes = report_generator.build_report(session.filename, session.df, entries, session.overall_analysis, language)
    filename = f"{report_generator.REPORT_NAME}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
