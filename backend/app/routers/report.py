"""Builds and streams a session's downloadable .pptx report -- entirely from
analyses already computed on the Analysis page (session.analysis_results).
Never triggers a new Analysis Agent run itself; a PM computes those on the
Analysis page first, and this router only reads whatever is already there.
The report's own closing-slide bullet points (see final_summary_agent.py)
are the one thing generated fresh here, from whichever analyses are
included."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.schemas import (
    EntryTranslation,
    LanguageOption,
    ReportSummaryResponse,
    ReportTranslationsResponse,
    SupportedLanguagesResponse,
)
from app.services.analysis import analysis_repository
from app.services.audit.audit_store import AuditSession, store
from app.services.report import final_summary_agent, report_generator, translation_service

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


def _get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session


def _report_ready_entries(
    session: AuditSession,
    session_id: str,
    entry_ids: list[str] | None,
    chart_type_overrides: dict[str, str] | None = None,
) -> list[dict]:
    """Definitions merged with their in-memory run result, limited to ones
    that actually finished successfully and (if entry_ids was given) were
    chosen for inclusion -- returned in `entry_ids`' own order when given,
    since that's the PM's chosen slide order (see ReportPage.tsx's drag
    reorder), not the repository's own internal order."""
    definitions = {d["id"]: d for d in analysis_repository.get_repository(session_id)}
    ids = entry_ids if entry_ids is not None else list(definitions.keys())

    ready = []
    for entry_id in ids:
        definition = definitions.get(entry_id)
        if definition is None:
            continue
        result = session.analysis_results.get(entry_id)
        if not result or result.run_status != "done":
            continue
        merged = dict(definition)
        merged.update(result.model_dump())
        if chart_type_overrides and entry_id in chart_type_overrides:
            merged["chart_type"] = chart_type_overrides[entry_id]
        ready.append(merged)
    return ready


@router.get("/{session_id}/summary", response_model=ReportSummaryResponse)
def get_report_summary(session_id: str, entry_id: list[str] | None = Query(default=None)) -> ReportSummaryResponse:
    """The Report page's own closing-slide bullet points, synthesized from
    the included analyses' interpretations -- recomputed on demand (never
    cached), since it changes with the PM's selection."""
    session = _get_session_or_404(session_id)
    entries = _report_ready_entries(session, session_id, entry_id)
    try:
        bullets = final_summary_agent.generate_summary(entries)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Report summary agent (OpenRouter) is unavailable: {exc}") from exc
    return ReportSummaryResponse(session_id=session_id, bullets=bullets)


@router.get("/{session_id}/translations", response_model=ReportTranslationsResponse)
def get_report_translations(
    session_id: str,
    language: str = Query(...),
    entry_id: list[str] | None = Query(default=None),
) -> ReportTranslationsResponse:
    """On-screen preview mirror of what build_report translates onto each
    slide -- lets the Report page show translated headings/interpretations
    before the PM downloads anything, using the same translate_entry_texts
    batch call the .pptx export itself uses, so the preview never drifts
    from what the download will actually say."""
    session = _get_session_or_404(session_id)
    if language != "en" and language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"'{language}' isn't a supported report language.")
    entries = _report_ready_entries(session, session_id, entry_id)
    phrases = report_generator.translate_entry_texts(entries, language)

    translations: dict[str, EntryTranslation] = {}
    for entry in entries:
        name = entry.get("name") or "Analysis"
        interpretation = entry.get("interpretation")
        translations[entry["id"]] = EntryTranslation(
            name=phrases.get(name, name),
            interpretation=phrases.get(interpretation, interpretation) if interpretation else None,
        )
    return ReportTranslationsResponse(translations=translations)


@router.get("/{session_id}/download")
def download_report(
    session_id: str,
    entry_id: list[str] | None = Query(default=None),
    chart_type: list[str] | None = Query(default=None),
    language: str = Query(default="en"),
):
    session = _get_session_or_404(session_id)
    overrides = (
        dict(zip(entry_id, chart_type)) if entry_id and chart_type and len(entry_id) == len(chart_type) else None
    )
    entries = _report_ready_entries(session, session_id, entry_id, overrides)
    if not entries:
        raise HTTPException(
            status_code=422,
            detail="No completed analyses to include in the report -- run some on the Analysis page first.",
        )
    if language != "en" and language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"'{language}' isn't a supported report language.")

    # A failed summary shouldn't block the whole export -- degrade to a
    # plain note instead (unlike /summary above, there's no retry loop here).
    try:
        summary_bullets = final_summary_agent.generate_summary(entries)
    except Exception:
        summary_bullets = ["Final summary is unavailable right now."]

    pptx_bytes = report_generator.build_report(session.filename, session.df, entries, summary_bullets, language)
    filename = f"{report_generator.REPORT_NAME}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
