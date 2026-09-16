import io
import json
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pptx import Presentation

from app.schemas import (
    AnalysisBriefRequest,
    AnalysisBriefResponse,
    AnalysisRequirement,
    AnalysisRequirementOutcome,
    AnalysisStoreResponse,
    ApplyPivotsRequest,
    AskQuestionRequest,
    ChartInterpretationResponse,
    DrillDownSuggestionsResponse,
    FormulaAnswerResponse,
    LanguageOption,
    OverallAnalysisReport,
    PivotDefinitionsSummary,
    PivotDrillDownRequest,
    PivotReport,
    ReportFilterScopeResponse,
    ReportFiltersResponse,
    ReportPreviewResponse,
    ReportSlidesResponse,
    ReportTemplateSummary,
    ReportTitlesResponse,
    SaveDefinitionRequest,
    SavedDefinition,
    SavedDefinitionsResponse,
    SetPivotSelectionRequest,
    SetReportFilterScopeRequest,
    SetReportFiltersRequest,
    SetReportSlidesRequest,
    SetReportTitleRequest,
    SetSavedScopeRequest,
    SuggestPivotsRequest,
    SuggestPivotsResponse,
    SupportedLanguagesResponse,
)
from app.services import (
    analysis_orchestrator,
    analysis_store,
    chart_interpretation_agent,
    drill_down_agent,
    formula_agent,
    overall_analysis,
    overall_analysis_agent,
    pivot_engine,
    pivot_suggester,
    report_generator,
    translation_service,
)
from app.services import custom_library_store
from app.services import pivot_definitions_store as pivot_defs_store
from app.services import report_template_store
from app.services.audit_store import AuditSession, store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session


def _combined_pivot_defs(session: AuditSession) -> list[dict]:
    """Every analysis definition that should be computed for this session,
    in the order they're applied: the uploaded Analysis Profile, then any
    saved custom analysis the user marked "keep as my regular" (see
    custom_library_store.py), then whatever this session added on top. Later
    groups win on an id clash -- a session's own edit of an analysis beats
    the saved copy, which beats the profile's. Anything the user unchecked
    on the Analysis page (session.excluded_pivot_ids) is filtered out last,
    regardless of which group it came from."""
    combined = custom_library_store.merge_definitions(
        list(pivot_defs_store.store.definitions or []),
        custom_library_store.store.regular_specs("pivots"),
        session.extra_pivot_defs,
    )
    if not session.excluded_pivot_ids:
        return combined
    excluded = set(session.excluded_pivot_ids)
    return [spec for spec in combined if spec.get("id") not in excluded]


def _to_pivot_report(session: AuditSession) -> PivotReport:
    return PivotReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        pivots=session.pivots + session.drill_down_pivots,
        skipped_notes=session.pivot_skipped_notes,
        pivot_filters=session.pivot_filter_state,
        excluded_pivot_ids=session.excluded_pivot_ids,
    )


def _find_pivot(session: AuditSession, pivot_id: str):
    return next((p for p in session.pivots + session.drill_down_pivots if p.id == pivot_id), None)


@router.post("/definitions", response_model=PivotDefinitionsSummary)
async def upload_pivot_definitions(file: UploadFile = File(...)) -> PivotDefinitionsSummary:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        pivots = pivot_defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or "analysis_profile.json"
    pivot_defs_store.store.set(filename, pivots)

    return PivotDefinitionsSummary(
        filename=filename,
        pivot_count=len(pivots),
        pivot_names=[p["name"] for p in pivots],
    )


@router.get("/definitions", response_model=PivotDefinitionsSummary)
def get_pivot_definitions() -> PivotDefinitionsSummary:
    if pivot_defs_store.store.definitions is None:
        raise HTTPException(status_code=404, detail="No Analysis Profile has been uploaded yet.")
    return PivotDefinitionsSummary(
        filename=pivot_defs_store.store.filename,
        pivot_count=len(pivot_defs_store.store.definitions),
        pivot_names=[p["name"] for p in pivot_defs_store.store.definitions],
    )


@router.post("/report-template", response_model=ReportTemplateSummary)
async def upload_report_template(file: UploadFile = File(...)) -> ReportTemplateSummary:
    """Optional -- a .pptx to use as the base for every downloaded report
    instead of the built-in layout (see report_generator.build_report). Not
    validated beyond "is it a real pptx" here; report_template_builder falls
    back to the first available layout for anything it can't name-match, so
    an unfamiliar template still produces a deck."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    try:
        Presentation(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Not a valid .pptx file: {exc}") from exc

    filename = file.filename or "report_template.pptx"
    report_template_store.store.set(filename, raw)
    return ReportTemplateSummary(filename=filename)


@router.get("/report-template", response_model=ReportTemplateSummary)
def get_report_template() -> ReportTemplateSummary:
    return ReportTemplateSummary(filename=report_template_store.store.filename)


@router.delete("/report-template", response_model=ReportTemplateSummary)
def clear_report_template() -> ReportTemplateSummary:
    report_template_store.store.clear()
    return ReportTemplateSummary(filename=None)


@router.get("/custom-pivots", response_model=SavedDefinitionsResponse)
def list_saved_pivots() -> SavedDefinitionsResponse:
    """Every custom analysis the user has saved, of either scope -- the
    Analysis page shows the "suggested" ones alongside the AI suggestions,
    and marks the "regular" ones as already part of every run."""
    return SavedDefinitionsResponse(
        items=[SavedDefinition(**item) for item in custom_library_store.store.entries("pivots")]
    )


@router.post("/custom-pivots", response_model=SavedDefinition)
def save_custom_pivot(body: SaveDefinitionRequest) -> SavedDefinition:
    """Persists one custom analysis to disk. `scope` is the user's choice
    between the two save options: "regular" (merged into every future run
    automatically) or "suggested" (kept in their list, added when they want
    it). Upserts by the definition's own id."""
    try:
        entry = custom_library_store.store.save("pivots", body.definition, body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SavedDefinition(**entry)


@router.post("/custom-pivots/{definition_id}/scope", response_model=SavedDefinition)
def set_saved_pivot_scope(definition_id: str, body: SetSavedScopeRequest) -> SavedDefinition:
    try:
        entry = custom_library_store.store.set_scope("pivots", definition_id, body.scope)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No saved analysis with that id.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SavedDefinition(**entry)


@router.delete("/custom-pivots/{definition_id}", response_model=SavedDefinitionsResponse)
def delete_saved_pivot(definition_id: str) -> SavedDefinitionsResponse:
    """Removes it from the library only. An analysis already computed for a
    running session stays there until that session recomputes."""
    try:
        custom_library_store.store.delete("pivots", definition_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No saved analysis with that id.") from exc
    return SavedDefinitionsResponse(
        items=[SavedDefinition(**item) for item in custom_library_store.store.entries("pivots")]
    )


@router.get("/languages", response_model=SupportedLanguagesResponse)
def get_supported_languages() -> SupportedLanguagesResponse:
    """Languages the downloaded report can be translated into (see
    translation_service.py) -- "en" (no translation, the default) plus
    whatever DeepL target languages that module currently lists."""
    languages = [LanguageOption(code="en", name="English")] + [
        LanguageOption(code=code, name=name)
        for code, (name, _) in sorted(translation_service.SUPPORTED_LANGUAGES.items(), key=lambda kv: kv[1][0])
    ]
    return SupportedLanguagesResponse(languages=languages, available=translation_service.is_available())


@router.post("/suggest", response_model=SuggestPivotsResponse)
def suggest_pivots(body: SuggestPivotsRequest) -> SuggestPivotsResponse:
    session = _get_session_or_404(body.session_id)
    try:
        suggestions = pivot_suggester.suggest_pivots(session.df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Pivot suggestion agent (Groq) is unavailable: {exc}") from exc
    return SuggestPivotsResponse(session_id=body.session_id, suggestions=suggestions)


@router.post("/{session_id}/pivots", response_model=PivotReport)
def apply_pivots(session_id: str, body: ApplyPivotsRequest | None = None) -> PivotReport:
    session = _get_session_or_404(session_id)
    if pivot_defs_store.store.definitions is None:
        raise HTTPException(
            status_code=422,
            detail="No Analysis Profile is available and the bundled default could not be loaded -- "
                   "upload one (with your pivot table definitions) before analysis can run.",
        )
    # `extra_pivots` omitted (None) means "leave the AI/custom pivots already
    # applied for this session alone" -- a caller that only wants to change
    # slicer filters (e.g. the Report page) doesn't have to resend the
    # Analysis page's full accepted list to avoid dropping them.
    if body is not None and body.extra_pivots is not None:
        session.extra_pivot_defs = body.extra_pivots

    # `pivot_filters` is merged per-pivot-id, not replaced wholesale -- a
    # caller touching one pivot's filters (or adding a shared filter across
    # several) shouldn't blow away filters already saved for pivots it
    # didn't mention. Callers that DO want to clear a pivot's filters must
    # send it explicitly with an empty list, not omit the key.
    if body is not None and body.pivot_filters:
        session.pivot_filter_state = {**session.pivot_filter_state, **body.pivot_filters}
    pivot_filters = session.pivot_filter_state

    results, skipped_notes = pivot_engine.apply_pivots(
        session.df, _combined_pivot_defs(session), pivot_filters=pivot_filters
    )
    session.pivots = results
    session.pivot_skipped_notes = skipped_notes
    return _to_pivot_report(session)


@router.get("/{session_id}/pivots", response_model=PivotReport)
def get_pivots(session_id: str) -> PivotReport:
    return _to_pivot_report(_get_session_or_404(session_id))


@router.post("/{session_id}/pivot-selection", response_model=PivotReport)
def set_pivot_selection(session_id: str, body: SetPivotSelectionRequest) -> PivotReport:
    """The Analysis page's "Defined" checkboxes -- a defined analysis the
    user unchecked is excluded from `_combined_pivot_defs` on every
    recompute until checked again. Replaces the whole exclusion set (same
    convention as /report-slides) and recomputes immediately so the
    unchecked chart disappears/reappears without a second round-trip."""
    session = _get_session_or_404(session_id)
    session.excluded_pivot_ids = list(dict.fromkeys(body.excluded_ids))
    results, skipped_notes = pivot_engine.apply_pivots(
        session.df, _combined_pivot_defs(session), pivot_filters=session.pivot_filter_state
    )
    session.pivots = results
    session.pivot_skipped_notes = skipped_notes
    return _to_pivot_report(session)


@router.get("/{session_id}/pivots/{pivot_id}/drill-down-suggestions", response_model=DrillDownSuggestionsResponse)
def get_pivot_drill_down_suggestions(session_id: str, pivot_id: str) -> DrillDownSuggestionsResponse:
    """Drill-down suggestions scoped to ONE chart's own rows (not every
    active pivot) -- click-on-an-analysis's "what should I look at next
    from this chart" step. Same drill_down_agent.py as the session-wide GET
    above, just handed only this one pivot."""
    session = _get_session_or_404(session_id)
    pivot = _find_pivot(session, pivot_id)
    if pivot is None:
        raise HTTPException(status_code=404, detail="No computed pivot with that id for this session.")
    highlights = overall_analysis.build_highlights(len(session.df), session.features, session.pivots)
    try:
        suggestions = drill_down_agent.suggest_drill_downs(len(session.df), highlights, [pivot])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Drill-down suggestion agent (Groq) is unavailable: {exc}") from exc
    if suggestions:
        analysis_store.store.add(session_id, "drill_down", pivot.name, suggestions)
    return DrillDownSuggestionsResponse(session_id=session_id, suggestions=suggestions)


@router.post("/{session_id}/pivots/{pivot_id}/drill-down/apply", response_model=FormulaAnswerResponse)
def apply_pivot_drill_down(session_id: str, pivot_id: str, body: PivotDrillDownRequest) -> FormulaAnswerResponse:
    """"Add" on a per-chart drill-down suggestion: answers it exactly like a
    direct "Ask a Question" (same formula_agent.py, template-or-custom-
    Python path), and -- when it comes back as a pivot table -- keeps it as
    a new, first-class analysis (id re-prefixed "drilldown_") so it shows up
    in the Analysis page's own list, with its own chart interpretation and
    its own further drill-downs (the same two endpoints above work on it
    unchanged, since it's just another entry in session.pivots +
    session.drill_down_pivots). A scalar/table answer (no chart shape) isn't
    force-fit into a pivot card -- it still comes back for display, just not
    persisted as one."""
    session = _get_session_or_404(session_id)
    if _find_pivot(session, pivot_id) is None:
        raise HTTPException(status_code=404, detail="No computed pivot with that id for this session.")
    try:
        answer = formula_agent.answer_question(session_id, body.suggestion, session.df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Formula agent (Groq) is unavailable: {exc}") from exc

    pivot_result = answer.pivot
    if pivot_result is not None:
        pivot_result = pivot_result.model_copy(update={"id": f"drilldown_{uuid.uuid4().hex[:8]}"})
        session.drill_down_pivots.append(pivot_result)

    return FormulaAnswerResponse(
        session_id=session_id, question=body.suggestion, mode=answer.mode,
        pivot=pivot_result, table=answer.table, value=answer.value, explanation=answer.explanation,
    )


MAX_AUTO_PIVOTS = 3  # cap on how many AI-suggested pivots a brief auto-applies (mirrors AI_SUGGESTED features' cap)
MAX_INTERPRETATIONS = 2  # cap on how many of those get an AI chart interpretation, to bound Groq calls per brief


def _pivot_is_duplicate(suggestion, existing_pivots: list) -> bool:
    """Same group-by shape + at least one overlapping metric as an already-
    active pivot counts as "already covered" -- cheap, deterministic, no
    extra Groq call, same spirit as kpi_store.find_equivalent for features."""
    sug_group = set(suggestion.group_by)
    sug_metrics = {m.output_label for m in suggestion.metrics}
    return any(
        set(p.group_by) == sug_group and sug_metrics & set(p.metric_labels)
        for p in existing_pivots
    )


@router.post("/client-brief", response_model=AnalysisBriefResponse)
def submit_analysis_brief(body: AnalysisBriefRequest) -> AnalysisBriefResponse:
    """Step 3's "AI-Assisted Analysis, one step at a time" flow, run in one
    shot from a Client Brief instead of a click per stop -- every piece is
    the existing agent/endpoint above:

      1. Chart Suggestion (pivot_suggester) -- up to MAX_AUTO_PIVOTS new
         pivots not already covered by one this session has are applied via
         the same pivot_engine every pivot in this app runs through. This is
         the AI-Suggested side -- driven by the data's own shape, not the
         brief's text.
      2. AI Summary (overall_analysis + overall_analysis_agent) -- same as
         GET /overall, recomputed over the now-current pivot set.
      3. Chart Interpretation (chart_interpretation_agent) -- for up to
         MAX_INTERPRETATIONS of the newly-applied pivots.
      4. Client-Requested Analyses (analysis_orchestrator) -- every DISTINCT
         analysis/chart/breakdown the brief explicitly asked for is
         extracted and resolved through formula_agent.answer_question (a
         pivot template first, sandboxed Python otherwise -- the SAME engine
         "Request an Analysis" and a chart's own drill-down "Add" already
         run through), then added to the session -- guaranteed already
         present, not merely suggested, mirroring feature_orchestrator's
         guarantee for an explicit client-requested feature. If the brief
         didn't parse into any distinct requirement (e.g. it's really just
         one short question), it falls back to answering the whole brief
         directly instead, same as before this existed.

    One step's agent being unavailable (Groq down/rate-limited) is caught
    and recorded in `errors` rather than aborting the rest -- whatever
    already succeeded is still returned."""
    session = _get_session_or_404(body.session_id)
    errors: list[str] = []

    suggested_pivots: list = []
    try:
        suggested_pivots = pivot_suggester.suggest_pivots(session.df)
    except Exception as exc:
        errors.append(f"Chart suggestion agent unavailable: {exc}")

    to_apply = [s for s in suggested_pivots if not _pivot_is_duplicate(s, session.pivots)][:MAX_AUTO_PIVOTS]
    if to_apply:
        session.extra_pivot_defs = session.extra_pivot_defs + [s.model_dump(exclude_none=True) for s in to_apply]
        results, skipped_notes = pivot_engine.apply_pivots(
            session.df, _combined_pivot_defs(session), pivot_filters=session.pivot_filter_state
        )
        session.pivots = results
        session.pivot_skipped_notes = skipped_notes
        errors.extend(skipped_notes)
    applied_ids = [s.id for s in to_apply if any(p.id == s.id for p in session.pivots)]

    highlights = overall_analysis.build_highlights(len(session.df), session.features, session.pivots)
    overall: OverallAnalysisReport | None = None
    try:
        narrative = overall_analysis_agent.generate_narrative(len(session.df), highlights)
        overall = OverallAnalysisReport(
            session_id=session.session_id, row_count=len(session.df), highlights=highlights, narrative=narrative
        )
        session.overall_analysis = overall
        analysis_store.store.add(
            session.session_id, "summary", "AI Summary",
            {"highlights": [h.model_dump() for h in highlights], "narrative": narrative},
        )
    except Exception as exc:
        errors.append(f"AI summary agent unavailable: {exc}")

    interpretations: dict[str, str] = {}
    for pivot in [p for p in session.pivots if p.id in applied_ids][:MAX_INTERPRETATIONS]:
        try:
            text = chart_interpretation_agent.interpret_pivot(pivot)
            interpretations[pivot.id] = text
            analysis_store.store.add(session.session_id, "chart_interpretation", pivot.name, text)
        except Exception as exc:
            errors.append(f"Chart interpretation unavailable for '{pivot.name}': {exc}")

    client_requirements: list[dict] = []
    try:
        client_requirements = analysis_orchestrator.extract_analysis_requirements(body.brief, session.df)
    except Exception as exc:
        errors.append(f"Analysis requirement extraction unavailable: {exc}")

    outcomes = []
    formula_answer: FormulaAnswerResponse | None = None
    if client_requirements:
        outcomes, new_pivots = analysis_orchestrator.resolve_analysis_requirements(
            session.session_id, client_requirements, session.df, session.pivots + session.drill_down_pivots
        )
        session.drill_down_pivots.extend(new_pivots)
        errors.extend(o.error for o in outcomes if o.status == "failed" and o.error)
    else:
        # The brief didn't parse into any distinct requirement -- likely a
        # single short question, not a multi-part brief -- so fall back to
        # answering it directly, same behavior as before this existed.
        try:
            answer = formula_agent.answer_question(session.session_id, body.brief, session.df)
            answer_pivot = answer.pivot
            if answer_pivot is not None:
                # Same treatment as /ask below: a brief's own direct question
                # that resolves to a chart is a User-Requested Analysis, not
                # a throwaway answer -- it stays on the page after this call.
                answer_pivot = answer_pivot.model_copy(update={"id": f"custom_pivot_{uuid.uuid4().hex[:8]}"})
                session.drill_down_pivots.append(answer_pivot)
            formula_answer = FormulaAnswerResponse(
                session_id=session.session_id, question=body.brief, mode=answer.mode,
                pivot=answer_pivot, table=answer.table, value=answer.value, explanation=answer.explanation,
            )
        except ValueError as exc:
            errors.append(f"Formula agent could not answer the brief directly: {exc}")
        except Exception as exc:
            errors.append(f"Formula agent unavailable: {exc}")

    return AnalysisBriefResponse(
        session_id=body.session_id,
        overall=overall,
        suggested_pivots=suggested_pivots,
        applied_pivot_ids=applied_ids,
        interpretations=interpretations,
        formula_answer=formula_answer,
        client_requirements=[AnalysisRequirement(**r) for r in client_requirements],
        outcomes=[AnalysisRequirementOutcome(**o.__dict__) for o in outcomes],
        pivot_report=_to_pivot_report(session),
        errors=errors,
    )


@router.get("/{session_id}/report-filters", response_model=ReportFiltersResponse)
def get_report_filters(session_id: str) -> ReportFiltersResponse:
    session = _get_session_or_404(session_id)
    return ReportFiltersResponse(session_id=session.session_id, filters=session.report_filters)


@router.post("/{session_id}/report-filters", response_model=ReportFiltersResponse)
def set_report_filters(session_id: str, body: SetReportFiltersRequest) -> ReportFiltersResponse:
    """The ONE shared filter set for the whole downloaded report -- replaces
    it wholesale (there's only one, unlike the per-pivot pivot_filters map).
    Report-time only -- never touches session.pivots. Selecting 2+ values
    for a column here means the report gets one slide per value for every
    pivot, instead of one slide combining them (see report_generator)."""
    session = _get_session_or_404(session_id)
    session.report_filters = body.filters
    return ReportFiltersResponse(session_id=session.session_id, filters=session.report_filters)


@router.get("/{session_id}/report-filter-scope", response_model=ReportFilterScopeResponse)
def get_report_filter_scope(session_id: str) -> ReportFilterScopeResponse:
    """Merges any explicit per-pivot overrides with report_generator's
    default scope exclusions (see DEFAULT_SCOPE_EXCLUSIONS) so the Report
    page's filter-scope chips reflect the same defaults the downloaded .pptx
    actually uses, without requiring the user to have touched a chip first."""
    session = _get_session_or_404(session_id)
    active_columns = [f.column for f in session.report_filters]
    scope = dict(session.pivot_filter_scope)
    for pivot in session.pivots:
        if pivot.id in scope:
            continue
        default = report_generator.resolve_default_scope(pivot.name, active_columns)
        if default is not None:
            scope[pivot.id] = default
    return ReportFilterScopeResponse(session_id=session.session_id, scope=scope)


@router.post("/{session_id}/report-filter-scope", response_model=ReportFilterScopeResponse)
def set_report_filter_scope(session_id: str, body: SetReportFilterScopeRequest) -> ReportFilterScopeResponse:
    """Which of the shared report_filters columns actually apply to ONE
    pivot -- e.g. pivot_1 scoped to just ["Country of Origin"] ignores
    Origin/Carrier/Product/departure-range even though they're set overall.
    `columns=None` clears the override (back to "every active column
    applies", the default). Only touches this one pivot id."""
    session = _get_session_or_404(session_id)
    if body.columns is None:
        session.pivot_filter_scope.pop(body.pivot_id, None)
    else:
        session.pivot_filter_scope[body.pivot_id] = body.columns
    return ReportFilterScopeResponse(session_id=session.session_id, scope=session.pivot_filter_scope)


@router.get("/{session_id}/report-titles", response_model=ReportTitlesResponse)
def get_report_titles(session_id: str) -> ReportTitlesResponse:
    session = _get_session_or_404(session_id)
    return ReportTitlesResponse(session_id=session.session_id, titles=session.report_titles)


@router.post("/{session_id}/report-titles", response_model=ReportTitlesResponse)
def set_report_title(session_id: str, body: SetReportTitleRequest) -> ReportTitlesResponse:
    """Purely cosmetic -- renames a pivot's slide heading in the downloaded
    report (and the prefix of any of its multiplied variants). `title=None`
    clears the override, back to the pivot's own name."""
    session = _get_session_or_404(session_id)
    if body.title is None or not body.title.strip():
        session.report_titles.pop(body.pivot_id, None)
    else:
        session.report_titles[body.pivot_id] = body.title.strip()
    return ReportTitlesResponse(session_id=session.session_id, titles=session.report_titles)


@router.get("/{session_id}/overall", response_model=OverallAnalysisReport)
def get_overall_analysis(session_id: str) -> OverallAnalysisReport:
    session = _get_session_or_404(session_id)
    highlights = overall_analysis.build_highlights(len(session.df), session.features, session.pivots)
    try:
        narrative = overall_analysis_agent.generate_narrative(len(session.df), highlights)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Overall analysis narrative agent (Groq) is unavailable: {exc}"
        ) from exc
    report = OverallAnalysisReport(
        session_id=session_id, row_count=len(session.df), highlights=highlights, narrative=narrative
    )
    session.overall_analysis = report
    analysis_store.store.add(session_id, "summary", "AI Summary", {"highlights": [h.model_dump() for h in highlights], "narrative": narrative})
    return report


# -- Step 3, 2·3·4: chart suggestion is /suggest above; chart interpretation
# and drill-down suggestions are the Insight Agent's other two stops in the
# numbered flow (see the frontend Analysis page for the 1-5 ordering).


@router.get("/{session_id}/pivots/{pivot_id}/interpretation", response_model=ChartInterpretationResponse)
def get_chart_interpretation(session_id: str, pivot_id: str, refresh: bool = False) -> ChartInterpretationResponse:
    """`refresh=false` (the default) returns the most recent interpretation
    already logged for this pivot in analysis_store.py -- e.g. one the
    Client Brief pipeline (/client-brief) computed automatically -- instead
    of spending another Groq call to say the same thing again. The
    "Re-interpret" button in the Analysis page's chart modal passes
    `refresh=true` to force a fresh take."""
    session = _get_session_or_404(session_id)
    pivot = _find_pivot(session, pivot_id)
    if pivot is None:
        raise HTTPException(status_code=404, detail="No computed pivot with that id for this session.")

    if not refresh:
        cached = next(
            (e for e in reversed(analysis_store.store.entries(session_id, "chart_interpretation")) if e["label"] == pivot.name),
            None,
        )
        if cached:
            return ChartInterpretationResponse(session_id=session_id, pivot_id=pivot_id, interpretation=cached["content"])

    try:
        interpretation = chart_interpretation_agent.interpret_pivot(pivot)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chart interpretation agent (Groq) is unavailable: {exc}") from exc
    analysis_store.store.add(session_id, "chart_interpretation", pivot.name, interpretation)
    return ChartInterpretationResponse(session_id=session_id, pivot_id=pivot_id, interpretation=interpretation)




# -- Step 3, 5: the Formula Agent. A drill-down suggestion or the user's own
# plain-language question either land here the same way.


@router.post("/{session_id}/ask", response_model=FormulaAnswerResponse)
def ask_question(session_id: str, body: AskQuestionRequest) -> FormulaAnswerResponse:
    """"Request an Analysis" -- the ONE user-requested entry point (a
    natural-language ask replaces the old separate "Add a Custom Analysis"
    form: both ultimately ran through a template match or sandboxed Python,
    so there's no need for two paths). A question that resolves to a chart
    is kept as a new, first-class "User-Requested" analysis (id re-prefixed
    "custom_pivot_") exactly like a per-chart drill-down's own "Add" button,
    rather than just shown once and discarded."""
    session = _get_session_or_404(session_id)
    try:
        answer = formula_agent.answer_question(session_id, body.question, session.df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Formula agent (Groq) is unavailable: {exc}") from exc

    pivot_result = answer.pivot
    if pivot_result is not None:
        pivot_result = pivot_result.model_copy(update={"id": f"custom_pivot_{uuid.uuid4().hex[:8]}"})
        session.drill_down_pivots.append(pivot_result)

    return FormulaAnswerResponse(
        session_id=session_id,
        question=body.question,
        mode=answer.mode,
        pivot=pivot_result,
        table=answer.table,
        value=answer.value,
        explanation=answer.explanation,
    )


@router.get("/{session_id}/analysis-store", response_model=AnalysisStoreResponse)
def get_analysis_store(session_id: str) -> AnalysisStoreResponse:
    """Everything Step 3's agents have already produced for this session --
    summaries, chart interpretations, drill-down suggestions, and past
    ask-a-question results (see services/analysis_store.py)."""
    entries = analysis_store.store.entries(session_id)
    return AnalysisStoreResponse(session_id=session_id, entries=entries)


def _require_pivots(session: AuditSession) -> None:
    if not session.pivots:
        raise HTTPException(
            status_code=422,
            detail="No pivot tables have been computed yet -- run the Analysis step before downloading a report.",
        )


def _validate_language(language: str) -> None:
    if language != "en" and language not in translation_service.SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail=f"Unsupported language '{language}'.")


@router.get("/{session_id}/report-slides", response_model=ReportSlidesResponse)
def get_report_slides(session_id: str) -> ReportSlidesResponse:
    session = _get_session_or_404(session_id)
    return ReportSlidesResponse(session_id=session.session_id, excluded_keys=session.excluded_slide_keys)


@router.post("/{session_id}/report-slides", response_model=ReportSlidesResponse)
def set_report_slides(session_id: str, body: SetReportSlidesRequest) -> ReportSlidesResponse:
    """Replaces the set of deselected slides wholesale -- the Report page
    always sends its whole current selection, and a key for a slide that no
    longer exists is harmless (it just never matches anything in the plan)."""
    session = _get_session_or_404(session_id)
    session.excluded_slide_keys = list(dict.fromkeys(body.excluded_keys))
    return ReportSlidesResponse(session_id=session.session_id, excluded_keys=session.excluded_slide_keys)


@router.get("/{session_id}/report-preview", response_model=ReportPreviewResponse)
def get_report_preview(session_id: str, language: str = "en") -> ReportPreviewResponse:
    """The exact slide list the .pptx would be built from right now -- same
    plan, same chart data, same headings (see report_generator.plan_report),
    just handed back as JSON for the Report page to draw instead of rendered
    into a file. Slides the user has deselected come back with
    `included: false` rather than being dropped, so the preview can still
    show them switched off."""
    session = _get_session_or_404(session_id)
    _require_pivots(session)
    _validate_language(language)

    slides, _ = report_generator.plan_report(
        source_label=report_generator.REPORT_NAME,
        df=session.df,
        pivots=session.pivots,
        definitions=_combined_pivot_defs(session),
        report_filters=[f.model_dump() for f in session.report_filters],
        pivot_filter_scope=session.pivot_filter_scope,
        report_titles=session.report_titles,
        overall=session.overall_analysis,
        language=language,
        excluded_keys=session.excluded_slide_keys,
    )
    return ReportPreviewResponse(session_id=session.session_id, language=language, slides=slides)


@router.get("/{session_id}/report")
def download_report(session_id: str, language: str = "en"):
    """Streams a .pptx built from every current pivot, each recomputed fresh
    from the raw data using the session's one shared report_filters (see
    /report-filters) -- a column with 2+ selected values there fans out into
    one slide per value, per pivot. Every chart is native, built fresh,
    never a picture. Slides deselected via /report-slides are left out.

    `language` (optional, default "en") translates the report's own fixed
    English phrases -- see report_generator.TRANSLATABLE_PHRASES -- plus the
    summary narrative, into one of the codes /languages lists; the
    underlying data (pivot/column names, category values) is never
    translated. If the translation API isn't configured or fails, the report
    still downloads, just in English."""
    session = _get_session_or_404(session_id)
    _require_pivots(session)
    _validate_language(language)

    pptx_bytes = report_generator.build_report(
        source_label=report_generator.REPORT_NAME,
        df=session.df,
        pivots=session.pivots,
        definitions=_combined_pivot_defs(session),
        report_filters=[f.model_dump() for f in session.report_filters],
        pivot_filter_scope=session.pivot_filter_scope,
        report_titles=session.report_titles,
        overall=session.overall_analysis,
        template_bytes=report_template_store.store.content,
        language=language,
        excluded_keys=session.excluded_slide_keys,
    )

    filename = f"{report_generator.REPORT_NAME}.pptx"
    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
