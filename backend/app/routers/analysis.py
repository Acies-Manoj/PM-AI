import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    AddCustomAnalysisRequest,
    AnalysisDefinitionsSummary,
    AnalysisRepositoryEntry,
    AnalysisRepositoryResponse,
    AnalysisResult,
    OverallAnalysisReport,
    SuggestAnalysisEntriesResponse,
)
from app.services import analysis_definitions_store as defs_store
from app.services import analysis_engine, analysis_repository, analysis_suggester, overall_analysis, overall_analysis_agent
from app.services.audit_store import AuditSession, store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


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
    "Run" has ever been clicked for it) into the full response shape."""
    result = session.analysis_results.get(definition["id"])
    merged = dict(definition)
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
        })
    return AnalysisRepositoryEntry(**merged)


@router.get("/repository/{session_id}", response_model=AnalysisRepositoryResponse)
def get_repository(session_id: str) -> AnalysisRepositoryResponse:
    session = _get_session_or_404(session_id)
    definitions = analysis_repository.get_repository(session_id)
    return AnalysisRepositoryResponse(
        session_id=session_id, entries=[_merge_entry(session, d) for d in definitions]
    )


@router.post("/repository/{session_id}/custom", response_model=AnalysisRepositoryEntry)
def add_custom_analysis(session_id: str, body: AddCustomAnalysisRequest) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Give the analysis a name.")
    if not body.calculation_intent.strip():
        raise HTTPException(status_code=422, detail="Describe what this analysis should show.")
    entry = analysis_repository.add_custom_entry(
        session_id, body.name.strip(), body.description.strip(), body.calculation_intent.strip(), body.input_columns
    )
    return _merge_entry(session, entry)


@router.post("/repository/{session_id}/suggest", response_model=SuggestAnalysisEntriesResponse)
def suggest_analyses(session_id: str) -> SuggestAnalysisEntriesResponse:
    session = _get_session_or_404(session_id)
    try:
        suggestions = analysis_suggester.suggest_analyses(session.df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Analysis suggestion agent (OpenRouter) is unavailable: {exc}") from exc
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
    result = AnalysisResult(
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
    )
    session.analysis_results[entry["id"]] = result
    return _merge_entry(session, entry)


@router.post("/repository/{session_id}/entries/{entry_id}/run", response_model=AnalysisRepositoryEntry)
def run_entry(session_id: str, entry_id: str) -> AnalysisRepositoryEntry:
    session = _get_session_or_404(session_id)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    if entry["status"] == "rejected":
        raise HTTPException(status_code=422, detail="This analysis was rejected and can't be run.")
    return _run_entry(session, session_id, entry)


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
