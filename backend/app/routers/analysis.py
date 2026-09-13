from fastapi import APIRouter, HTTPException

from app.schemas import (
    AnalysisState,
    AnalysisStep,
    ComputeRequest,
    NextStepRequest,
    StartAnalysisRequest,
)
from app.services import formula_agent, insight_agent, sandbox_executor
from app.services.analysis_store import store as analysis_store
from app.services.audit_store import store as audit_store

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_STEP_SEQUENCE = [
    "summary",
    "chart_suggestion",
    "chart_interpretation",
    "drill_down",
    "formula_spec",
]


def _flagged_summary(session_id: str) -> str:
    session = audit_store.get(session_id)
    if not session:
        return "No session data."
    if session.screening_report:
        r = session.screening_report
        trips_preview = [t.trip_id for t in r.flagged_trips[:5] if t.trip_id]
        return (
            f"{r.flagged_count} trips flagged out of {r.total_trips} total. "
            f"Product mean temps: {r.product_means}. "
            f"Sample flagged trip IDs: {trips_preview}. "
            f"Notes: {'; '.join(r.screening_notes)}."
        )
    cols = [str(c) for c in session.df.columns[:15]]
    return f"Audited data: {len(session.df)} rows. Columns: {', '.join(cols)}."


def _to_state(a) -> AnalysisState:
    return AnalysisState(
        analysis_id=a.analysis_id,
        session_id=a.session_id,
        brief=a.brief,
        steps=a.steps,
        status=a.status,
    )


@router.post("/start", response_model=AnalysisState)
def start_analysis(body: StartAnalysisRequest) -> AnalysisState:
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    if not body.brief.strip():
        raise HTTPException(status_code=422, detail="Brief cannot be empty.")

    flagged_summary = _flagged_summary(body.session_id)
    analysis = analysis_store.create(body.session_id, body.brief.strip(), flagged_summary)

    try:
        result = insight_agent.run_step("summary", analysis.brief, session.df, analysis.flagged_summary, [])
        analysis.steps.append(AnalysisStep(
            step_number=1,
            step_type="summary",
            content=result.content,
            chart_type=result.chart_type,
            drill_down_suggestions=result.drill_down_suggestions,
        ))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Insight agent unavailable: {exc}") from exc

    return _to_state(analysis)


@router.get("/{analysis_id}", response_model=AnalysisState)
def get_analysis(analysis_id: str) -> AnalysisState:
    a = analysis_store.get(analysis_id)
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    return _to_state(a)


@router.post("/{analysis_id}/next", response_model=AnalysisState)
def next_step(analysis_id: str, body: NextStepRequest) -> AnalysisState:
    a = analysis_store.get(analysis_id)
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    session = audit_store.get(a.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    completed = {s.step_type for s in a.steps}
    next_type = next((t for t in _STEP_SEQUENCE if t not in completed), None)
    if not next_type:
        a.status = "complete"
        return _to_state(a)
    try:
        prior = [
            {"step_number": s.step_number, "step_type": s.step_type, "content": s.content}
            for s in a.steps
        ]
        result = insight_agent.run_step(
            next_type, a.brief, session.df, a.flagged_summary, prior, user_ask=body.user_ask
        )
        a.steps.append(AnalysisStep(
            step_number=len(a.steps) + 1,
            step_type=next_type,
            content=result.content,
            chart_type=result.chart_type,
            drill_down_suggestions=result.drill_down_suggestions,
        ))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Insight agent unavailable: {exc}") from exc
    if len(a.steps) >= len(_STEP_SEQUENCE):
        a.status = "complete"
    return _to_state(a)


@router.post("/{analysis_id}/compute", response_model=AnalysisState)
def compute_formula(analysis_id: str, body: ComputeRequest) -> AnalysisState:
    a = analysis_store.get(analysis_id)
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    session = audit_store.get(a.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")

    context = "\n".join(s.content for s in a.steps[-3:])
    description, code = formula_agent.generate_formula_code(body.ask, session.df, context)

    if not code:
        raise HTTPException(status_code=502, detail="Formula agent could not generate working code.")

    result_dict, error = sandbox_executor.run_formula_code(code, session.df)
    if error:
        raise HTTPException(status_code=422, detail=f"Formula execution failed: {error}")

    a.validated_results.append(result_dict)
    a.steps.append(AnalysisStep(
        step_number=len(a.steps) + 1,
        step_type="formula_spec",
        content=f"Computed: {description}",
        formula_code=code,
        compute_result=result_dict,
    ))
    return _to_state(a)
