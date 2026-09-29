import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    AddCustomAnalysisRequest,
    AnalysisDefinitionsSummary,
    AnalysisDraft,
    AnalysisDrilldownSuggestion,
    AnalysisRepositoryEntry,
    AnalysisRepositoryResponse,
    AnalysisResult,
    DraftAnalysisRequest,
    FilterAnalysisRequest,
    OverallAnalysisReport,
    SuggestAnalysisEntriesResponse,
)
from app.services.analysis import analysis_definitions_store as defs_store
from app.services.analysis import (
    analysis_agent,
    analysis_designer,
    analysis_engine,
    analysis_filters,
    analysis_repository,
    analysis_suggester,
    analysis_templates,
    overall_analysis,
    overall_analysis_agent,
)
from app.services.analysis.analysis_agent import AnalysisComputation
from app.services.audit.audit_store import AuditSession, store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])
logger = logging.getLogger(__name__)


def _get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session


@router.post("/definitions", response_model=AnalysisDefinitionsSummary)
async def upload_analysis_definitions(file: UploadFile = File(...)) -> AnalysisDefinitionsSummary:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        analyses = defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or "analysis_profile.json"
    defs_store.store.set(filename, analyses)

    return AnalysisDefinitionsSummary(
        filename=filename,
        analysis_count=len(analyses),
        analysis_names=[a["name"] for a in analyses],
    )


@router.get("/definitions", response_model=AnalysisDefinitionsSummary)
def get_analysis_definitions() -> AnalysisDefinitionsSummary:
    if defs_store.store.definitions is None:
        raise HTTPException(status_code=404, detail="No Analysis Profile has been uploaded yet.")
    return AnalysisDefinitionsSummary(
        filename=defs_store.store.filename,
        analysis_count=len(defs_store.store.definitions),
        analysis_names=[a["name"] for a in defs_store.store.definitions],
    )


def _merge_entry(session: AuditSession, definition: dict) -> AnalysisRepositoryEntry:
    """Merges a repository definition with its in-memory run result (if
    "Run" has ever been clicked for it) into the full response shape. Filter
    options are computed from the CURRENT data on every read."""
    result = session.analysis_results.get(definition["id"])
    merged = dict(definition)
    merged["template_summary"] = analysis_templates.summarize(definition.get("template"))
    # A custom entry already has its own saved filters; every other source
    # only has them once a run has discovered them (see analysis_engine).
    filter_defs = definition.get("filters") or (result.filters if result else None) or []
    merged["filters"] = analysis_filters.options(session.df, filter_defs)
    if result:
        merged.update({
            "run_status": result.run_status,
            "plan_text": result.plan_text,
            "generated_code": result.generated_code,
            "result_table": result.result_table,
            "result_columns": result.result_columns,
            "chart_type": result.chart_type,
            "chart_spec": result.chart_spec,
            "interpretation": result.interpretation,
            "error": result.error,
            "drilldown_suggestions": result.drilldown_suggestions,
            "computation_mode": result.computation_mode,
            "notes": result.notes,
        })
        # A designed entry keeps the PM's chosen chart; every other entry
        # shows the chart its run picked from the logic before computing.
        if not definition.get("chart_recommendation") and result.chart_recommendation:
            merged["chart_recommendation"] = result.chart_recommendation
        # Same for the template: every source can now run on one.
        if not definition.get("template") and result.template:
            merged["template_summary"] = analysis_templates.summarize(result.template)
    return AnalysisRepositoryEntry(**merged)


@router.get("/repository/{session_id}", response_model=AnalysisRepositoryResponse)
def get_repository(session_id: str) -> AnalysisRepositoryResponse:
    session = _get_session_or_404(session_id)
    definitions = analysis_repository.get_repository(session_id)
    return AnalysisRepositoryResponse(
        session_id=session_id, entries=[_merge_entry(session, d) for d in definitions]
    )


@router.post("/repository/{session_id}/draft", response_model=AnalysisDraft)
def draft_analysis(session_id: str, body: DraftAnalysisRequest) -> AnalysisDraft:
    """Turns the PM's description into reviewable computation logic, a
    template match (or code generation), a chart recommendation and
    filters. Nothing is saved -- the PM confirms via /custom."""
    session = _get_session_or_404(session_id)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Give the analysis a name.")
    if not body.description.strip():
        raise HTTPException(status_code=422, detail="Describe what this analysis should show.")
    try:
        draft = analysis_designer.draft_analysis(body.name.strip(), body.description.strip(), session.df, body.formula)
    except Exception as exc:
        logger.exception("Analysis designer failed for session %s", session_id)
        raise HTTPException(
            status_code=502, detail="Couldn't draft the computation logic right now. Please try again."
        ) from exc
    return AnalysisDraft(**draft)


@router.post("/repository/{session_id}/custom", response_model=AnalysisRepositoryEntry)
def add_custom_analysis(session_id: str, body: AddCustomAnalysisRequest) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Give the analysis a name.")
    if not body.calculation_intent.strip():
        raise HTTPException(status_code=422, detail="Describe what this analysis should show.")
    template, chart_recommendation, filters = analysis_designer.finalize_custom(
        session.df, body.template, body.chart_type, body.chart_reason,
        [a.model_dump() for a in body.chart_alternatives], body.filters,
    )
    formula = body.formula.strip() if body.formula and body.formula.strip() else None
    entry = analysis_repository.add_custom_entry(
        session_id, body.name.strip(), body.description.strip(), body.calculation_intent.strip(), body.input_columns,
        formula=formula, template=template, chart_recommendation=chart_recommendation, filters=filters,
    )
    return _merge_entry(session, entry)


@router.post("/repository/{session_id}/suggest", response_model=SuggestAnalysisEntriesResponse)
def suggest_analyses(session_id: str) -> SuggestAnalysisEntriesResponse:
    session = _get_session_or_404(session_id)
    try:
        suggestions = analysis_suggester.suggest_analyses(session.df, analysis_repository.get_repository(session_id))
    except Exception as exc:
        logger.exception("Analysis suggestion agent failed for session %s", session_id)
        raise HTTPException(
            status_code=502, detail="Analysis suggestion agent is unavailable right now. Please try again."
        ) from exc
    new_entries = analysis_repository.add_ai_suggested_entries(session_id, suggestions)
    return SuggestAnalysisEntriesResponse(session_id=session_id, entries=[_merge_entry(session, e) for e in new_entries])


@router.post("/repository/{session_id}/entries/{entry_id}/accept", response_model=AnalysisRepositoryEntry)
def accept_entry(session_id: str, entry_id: str) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    entry = analysis_repository.set_entry_status(session_id, entry_id, "approved")
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    return _merge_entry(session, entry)


@router.post("/repository/{session_id}/entries/{entry_id}/reject", response_model=AnalysisRepositoryEntry)
def reject_entry(session_id: str, entry_id: str) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    entry = analysis_repository.set_entry_status(session_id, entry_id, "rejected")
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    return _merge_entry(session, entry)


def _run_entry(session: AuditSession, session_id: str, entry: dict) -> AnalysisRepositoryEntry:
    """Runs the Analysis Agent for one entry and stores the result on the
    session, in-memory. Never raises on an agent-side failure -- that's
    recorded as run_status="error" so one entry's failure never blocks the
    rest of the page, mirroring the feature system's skipped_notes
    philosophy."""
    computation = analysis_engine.run_analysis(session_id, entry, session.df)
    session.analysis_results[entry["id"]] = _to_result(entry, computation)
    return _merge_entry(session, entry)


def _to_result(entry: dict, computation: AnalysisComputation) -> AnalysisResult:
    return AnalysisResult(
        id=entry["id"],
        run_status="error" if computation.error and computation.result_table is None else "done",
        plan_text=computation.plan_text,
        generated_code=computation.generated_code,
        result_table=computation.result_table,
        result_columns=computation.result_columns,
        chart_type=computation.chart_type,
        chart_spec=computation.chart_spec,
        interpretation=computation.interpretation,
        error=computation.error,
        drilldown_suggestions=[
            {"id": f"{entry['id']}_dd{i}", **d} for i, d in enumerate(computation.drilldown_suggestions or [])
        ],
        computation_mode=computation.computation_mode if computation.result_table is not None else None,
        notes=computation.notes,
        chart_recommendation=computation.chart_recommendation,
        template=computation.template,
        filters=computation.filters,
    )


@router.post("/repository/{session_id}/entries/{entry_id}/run", response_model=AnalysisRepositoryEntry)
def run_entry(session_id: str, entry_id: str) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    if entry["status"] == "rejected":
        raise HTTPException(status_code=422, detail="This analysis was rejected and can't be run.")
    return _run_entry(session, session_id, entry)


@router.post("/repository/{session_id}/entries/{entry_id}/filter", response_model=AnalysisRepositoryEntry)
def filter_entry(session_id: str, entry_id: str, body: FilterAnalysisRequest) -> AnalysisRepositoryEntry:
    """A filtered VIEW of an already-run analysis, for its chart's filter
    controls. Never calls an LLM and never replaces the stored (unfiltered)
    result -- the report and the repository always use the unfiltered run.
    The interpretation and drilldowns shown are the unfiltered run's."""
    session = _get_session_or_404(session_id)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    base = session.analysis_results.get(entry_id)
    if base is None or base.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before filtering it.")

    applied = analysis_filters.active(body.filters, entry.get("filters") or [])
    if not applied:
        return _merge_entry(session, entry)
    computation = analysis_engine.filter_analysis(session_id, entry, session.df, body.filters, base.chart_type)
    view = _to_result(entry, computation)
    view.interpretation = base.interpretation
    view.drilldown_suggestions = base.drilldown_suggestions

    merged = _merge_entry(session, entry).model_dump()
    # chart_recommendation comes from _merge_entry above (the stored run's),
    # not from the filtered view.
    merged.update(view.model_dump(exclude={"id", "chart_recommendation", "template"}))
    merged["applied_filters"] = applied
    return AnalysisRepositoryEntry(**merged)


@router.post("/repository/{session_id}/entries/{entry_id}/drilldowns/{drilldown_id}/trigger", response_model=AnalysisRepositoryEntry)
def trigger_drilldown(session_id: str, entry_id: str, drilldown_id: str) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    parent_result = session.analysis_results.get(entry_id)
    if parent_result is None:
        raise HTTPException(status_code=404, detail="This analysis hasn't been run yet -- run it before exploring a drilldown.")

    suggestion = next((d for d in parent_result.drilldown_suggestions if d.id == drilldown_id), None)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Drilldown suggestion not found for this analysis.")
    if suggestion.triggered:
        child = analysis_repository.get_entry(session_id, suggestion.child_entry_id)
        if child is not None:
            return _merge_entry(session, child)

    child_entry = analysis_repository.add_drilldown_entry(session_id, entry_id, suggestion.model_dump())
    suggestion.triggered = True
    suggestion.child_entry_id = child_entry["id"]

    return _run_entry(session, session_id, child_entry)


@router.post("/repository/{session_id}/entries/{entry_id}/drilldowns/suggest-more", response_model=AnalysisRepositoryEntry)
def suggest_more_drilldowns(session_id: str, entry_id: str) -> AnalysisRepositoryEntry:
    """Asks the Analysis Agent for up to 3 more follow-ups, different from the
    ones this analysis already has, and appends them to its suggestions."""
    session = _get_session_or_404(session_id)
    entry = analysis_repository.get_entry(session_id, entry_id)
    result = session.analysis_results.get(entry_id)
    if entry is None or result is None or result.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before asking for more drill-downs.")

    existing = result.drilldown_suggestions
    try:
        fresh = analysis_agent.suggest_drilldowns(
            entry,
            {"plan": result.plan_text or entry.get("calculation_intent") or entry["name"]},
            analysis_agent._table_sample_block(result.result_table or []),
            result.interpretation or "",
            analysis_agent.describe_columns(session.df),
            parent_chart_type=result.chart_type,
            avoid=[d.name for d in existing],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't get more drill-down suggestions: {exc}") from exc

    seen = {d.name.strip().lower() for d in existing}
    next_index = len(existing)
    for spec in fresh:
        if spec["name"].strip().lower() in seen:
            continue
        seen.add(spec["name"].strip().lower())
        existing.append(AnalysisDrilldownSuggestion(id=f"{entry_id}_dd{next_index}", **spec))
        next_index += 1
    return _merge_entry(session, entry)


@router.get("/{session_id}/overall", response_model=OverallAnalysisReport)
def get_overall_analysis(session_id: str) -> OverallAnalysisReport:
    session = _get_session_or_404(session_id)
    definitions = analysis_repository.get_repository(session_id)
    done_entries = [
        _merge_entry(session, d).model_dump()
        for d in definitions
        if session.analysis_results.get(d["id"], None) and session.analysis_results[d["id"]].run_status == "done"
    ]
    highlights = overall_analysis.build_highlights(len(session.df), session.features, done_entries)
    try:
        narrative = overall_analysis_agent.generate_narrative(len(session.df), highlights)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Overall analysis narrative agent (OpenRouter) is unavailable: {exc}"
        ) from exc
    report = OverallAnalysisReport(
        session_id=session_id, row_count=len(session.df), highlights=highlights, narrative=narrative
    )
    session.overall_analysis = report
    return report
