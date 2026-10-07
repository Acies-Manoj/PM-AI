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
from app.services.analysis import analysis_repository
from app.services.audit.audit_store import AuditSession, get_or_404
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


MAX_SUBTITLE_CHARS = 110
MAX_SUBTITLE_VALUES = 3


def _drilldown_subtitle(chain: dict) -> str:
    """Short filter/rank line for a drill-down slide, e.g. 'Table Grapes - Top 3
    Origin by trips' or 'Origins: A, B, C +2 - Top 3 Carrier by trips, with %
    in spec'."""
    values = [str(v) for v in chain.get("focus_values") or []]
    if len(values) > 1:
        shown = ", ".join(values[:MAX_SUBTITLE_VALUES])
        extra = len(values) - MAX_SUBTITLE_VALUES
        focus = f"{chain.get('focus_dimension') or 'Value'}s: {shown}" + (f" +{extra}" if extra > 0 else "")
    else:
        focus = values[0] if values else (chain.get("focus_label") or "")

    rank = chain.get("rank") or {}
    dims = " x ".join(chain.get("dimensions") or [chain.get("dimension") or ""])
    by = "% in spec" if rank.get("by") == "pct_in_spec" else "trips"
    if rank.get("mode", "all") == "all":
        rank_text = f"{dims} by {by}"
    else:
        rank_text = f"{'Bottom' if rank.get('mode') == 'bottom' else 'Top'} {rank.get('n', 3)} {dims} by {by}"
    rank_text = rank_text.replace("  ", " ")
    if chain.get("metric") == "pct_in_spec" and rank.get("by") != "pct_in_spec":
        rank_text += ", with % in spec"
    elif chain.get("metric") in ("mean", "sum", "median", "max", "min") and chain.get("metric_column"):
        from app.services.analysis import analysis_drilldown
        rank_text += f", with {analysis_drilldown.agg_label(chain['metric'], chain['metric_column']).lower()}"

    text = f"{focus} - {rank_text}" if focus else rank_text
    if len(text) > MAX_SUBTITLE_CHARS:
        text = text[: MAX_SUBTITLE_CHARS - 1].rstrip() + "…"
    return text


def _report_ready_entries(
    session: AuditSession,
    session_id: str,
    entry_ids: list[str] | None,
    chart_type_overrides: dict[str, str] | None = None,
    include_stale: bool = False,
) -> list[dict]:
    """Definitions merged with their in-memory run result, limited to ones
    that actually finished successfully and (if entry_ids was given) were
    chosen for inclusion -- returned as a TREE: each root in the PM's chosen
    order (`entry_ids`' own order when given, see ReportPage.tsx's drag
    reorder, else the repository's), each followed depth-first by its
    drill-down levels (siblings in the PM's order among themselves), so slides
    read 1, 2, 2.1, 2.1.1, 2.2, 3. A drill-down can never precede its parent;
    one whose parent isn't included becomes a root (keeping its subtitle). Each entry gains
    `slide_number`, `chain_level`, `parent_slide_number`, `subtitle` (drill-
    downs only) and `stale`. Stale levels (their own or an ancestor's
    filter/rank changed since they were built) are left out unless
    `include_stale` -- the download and summary must never present them."""
    all_defs = analysis_repository.get_repository(session_id)
    definitions = {d["id"]: d for d in all_defs}
    position = {eid: i for i, eid in enumerate(entry_ids)} if entry_ids is not None else {}
    creation = {d["id"]: i for i, d in enumerate(all_defs)}

    def sort_key(eid: str) -> int:
        return position.get(eid, creation[eid])

    def is_stale(entry_id: str) -> bool:
        seen: set[str] = set()
        while entry_id in definitions and entry_id not in seen:
            seen.add(entry_id)
            d = definitions[entry_id]
            if (d.get("chain") or {}).get("stale"):
                return True
            entry_id = d.get("parent_id") if d.get("chain") else None
        return False

    candidates: dict[str, dict] = {}
    for entry_id in (entry_ids if entry_ids is not None else list(definitions.keys())):
        definition = definitions.get(entry_id)
        if definition is None or entry_id in candidates:
            continue
        if definition.get("status") != "approved":
            continue  # a pending or rejected drill-down path level is never in the report
        result = session.analysis_results.get(entry_id)
        if not result or result.run_status != "done":
            continue
        stale = is_stale(entry_id)
        if stale and not include_stale:
            continue
        merged = dict(definition)
        merged.update(result.model_dump())
        merged["stale"] = stale
        if chart_type_overrides and entry_id in chart_type_overrides:
            merged["chart_type"] = chart_type_overrides[entry_id]
        candidates[entry_id] = merged

    # Effective parent: only when the parent is itself included.
    children: dict[str | None, list[str]] = {}
    for entry_id, entry in candidates.items():
        parent = entry.get("parent_id") if entry.get("chain") else None
        children.setdefault(parent if parent in candidates else None, []).append(entry_id)
    for siblings in children.values():
        siblings.sort(key=sort_key)

    ready: list[dict] = []

    def walk(parent_id: str | None, prefix: str, parent_number: str | None) -> None:
        for i, entry_id in enumerate(children.get(parent_id, []), start=1):
            entry = candidates[entry_id]
            number = f"{prefix}.{i}" if prefix else str(i)
            chain = entry.get("chain")
            entry["slide_number"] = number
            entry["chain_level"] = chain["level"] if chain else 1
            entry["parent_slide_number"] = parent_number
            entry["subtitle"] = _drilldown_subtitle(chain) if chain else None
            ready.append(entry)
            walk(entry_id, number, number)

    walk(None, "", None)
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
