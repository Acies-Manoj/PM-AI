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
    ReportExportRequest,
    LanguageOption,
    ReportSummaryResponse,
    ReportTranslationsResponse,
    TranslateTextsRequest,
    TranslateTextsResponse,
    SupportedLanguagesResponse,
)
from app.services.analysis import analysis_drilldown
from app.services.audit.audit_store import get_or_404
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


_get_session_or_404 = get_or_404
_report_ready_entries = analysis_drilldown.report_ready_entries


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
    entries = _report_ready_entries(session, session_id, entry_id, include_stale=True)
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


@router.post("/{session_id}/export")
def export_report(session_id: str, body: ReportExportRequest):
    """Like GET /download, but for a deck the PM edited in the Report preview: the slide order, any edited
    titles/explanations/captions, the cover text and the summary bullets all come from the request body.
    Slides the PM deleted are simply not in `body.slides`."""
    session = _get_session_or_404(session_id)
    if body.language != "en" and body.language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"'{body.language}' isn't a supported report language.")

    entry_ids = [s.entry_id for s in body.slides]
    overrides = {s.entry_id: s.chart_type for s in body.slides if s.chart_type}
    entries = _report_ready_entries(session, session_id, entry_ids, overrides)
    if not entries:
        raise HTTPException(
            status_code=422,
            detail="No completed analyses to include in the report -- run some on the Analysis page first.",
        )
    edits = {s.entry_id: s for s in body.slides}
    for entry in entries:
        edit = edits.get(entry["id"])
        if edit is None:
            continue
        if edit.heading is not None:
            entry["edit_heading"] = edit.heading.strip() or None
        if edit.explanation is not None:
            entry["edit_explanation"] = edit.explanation
        if edit.caption is not None:
            entry["edit_caption"] = edit.caption

    if body.summary_bullets is not None:
        summary_bullets = [b.strip() for b in body.summary_bullets if b.strip()]
    else:
        try:
            summary_bullets = final_summary_agent.generate_summary(entries)
        except Exception:
            summary_bullets = ["Final summary is unavailable right now."]

    pptx_bytes = report_generator.build_report(
        session.filename, session.df, entries, summary_bullets, body.language,
        cover_title=(body.cover_title or "").strip() or None, cover_subtitle=body.cover_subtitle,
        custom_slides=[{"heading": c.heading, "bullets": c.bullets} for c in body.custom_slides],
    )
    filename = f"{report_generator.REPORT_NAME}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/translate", response_model=TranslateTextsResponse)
def translate_texts(body: TranslateTextsRequest) -> TranslateTextsResponse:
    """Translates free text for the Report page -- used for the closing-summary bullets, so the preview and
    the export both show the summary in the chosen language. Falls back to the original text on any failure."""
    if body.language != "en" and body.language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"'{body.language}' isn't a supported report language.")
    return TranslateTextsResponse(translations=translation_service.translate_many(body.texts, body.language))
