import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.schemas import (
    AddCustomAnalysisRequest,
    AnalysisDefinitionsSummary,
    AnalysisDraft,
    AnalysisDrilldownSuggestion,
    AnalysisRepositoryEntry,
    AnalysisRepositoryResponse,
    AnalysisResult,
    ConfirmDrilldownRequest,
    DraftAnalysisRequest,
    DrilldownOptions,
    DrilldownProposal,
    DrilldownRank,
    FilterAnalysisRequest,
    OverallAnalysisReport,
    SelectRequiredFeatureRequest,
    SuggestAnalysisEntriesResponse,
)
from app.services.analysis import analysis_definitions_store as defs_store
from app.services.analysis import (
    analysis_agent,
    analysis_dependencies,
    analysis_designer,
    analysis_drilldown,
    analysis_drilldown_agent,
    analysis_engine,
    analysis_filters,
    analysis_repository,
    analysis_suggester,
    analysis_templates,
    overall_analysis,
    overall_analysis_agent,
)
from app.services.analysis.analysis_agent import AnalysisComputation
from app.routers import deps
from app.routers.deps import User, get_user
from app.services.audit.audit_store import AuditSession, store
from app.services.common import request_context
from app.services.common.audit_log import log_event
from app.services.features import feature_repository

router = APIRouter(prefix="/api/analysis", tags=["analysis"])
# "One slide per value" creates this many sibling levels at most (each is an LLM run).
MAX_SPLIT_SLIDES = 6
logger = logging.getLogger(__name__)


@router.post("/definitions", response_model=AnalysisDefinitionsSummary)
async def upload_analysis_definitions(file: UploadFile = File(...), user: User = Depends(get_user)) -> AnalysisDefinitionsSummary:
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
    defs_store.save(user.id, filename, analyses)

    return AnalysisDefinitionsSummary(
        filename=filename,
        analysis_count=len(analyses),
        analysis_names=[a["name"] for a in analyses],
    )


@router.get("/definitions", response_model=AnalysisDefinitionsSummary)
def get_analysis_definitions(user: User = Depends(get_user)) -> AnalysisDefinitionsSummary:
    filename, definitions = defs_store.load(user.id)
    if definitions is None:
        raise HTTPException(status_code=404, detail="No Analysis Profile has been uploaded yet.")
    return AnalysisDefinitionsSummary(
        filename=filename,
        analysis_count=len(definitions),
        analysis_names=[a["name"] for a in definitions],
    )


# A drill-down level offers every column that can be selected as a filter -- the
# same pool as the X-axis columns -- capped only so the bar stays usable.
MAX_LEVEL_FILTERS = 30
_LEVEL_FILTER_CACHE: dict[tuple, list[dict]] = {}


def _level_filter_defs(session_id: str, session: AuditSession) -> list[dict]:
    """Filter columns for a drill-down level: Product, Origin, Carrier, Mode,
    engineered features and every other usable categorical column. Never
    trimmed to fit the chart -- a level's own X-axis columns, and the value it
    is narrowed to, stay filterable."""
    # Keyed by session version + column set (not id(df): a reloaded session gets a new frame object).
    key = (session_id, session.version, hash(tuple(session.df.columns)))
    if key not in _LEVEL_FILTER_CACHE:
        if len(_LEVEL_FILTER_CACHE) > 32:
            _LEVEL_FILTER_CACHE.clear()
        columns = analysis_drilldown_agent.candidate_dimensions(session.df, set(), _feature_columns(session_id, session))
        defs = analysis_filters.build_defs(
            [{"column": c, "reason": "Narrow this drill-down"} for c in columns], session.df, limit=MAX_LEVEL_FILTERS,
        )
        _LEVEL_FILTER_CACHE[key] = [d.model_dump() for d in defs]
    return _LEVEL_FILTER_CACHE[key]


def _level_scope(session: AuditSession, definition: dict):
    """The rows a level covers, so its filter lists only values that exist there."""
    try:
        return analysis_drilldown._apply(session.df, (definition.get("chain") or {}).get("where") or [])
    except analysis_templates.TemplateError:
        return session.df


def _merge_entry(session: AuditSession, definition: dict) -> AnalysisRepositoryEntry:
    """Merges a repository definition with its in-memory run result (if
    "Run" has ever been clicked for it) into the full response shape. Filter
    options are computed from the CURRENT data on every read."""
    result = session.analysis_results.get(definition["id"])
    merged = dict(definition)
    resolved = analysis_dependencies.resolve(session.session_id, definition, session.df)
    merged["required_features"] = resolved
    merged["dependencies_satisfied"] = not analysis_dependencies.unmet(resolved)
    merged["dependency_message"] = analysis_dependencies.block_message(resolved)
    merged["template_summary"] = analysis_templates.summarize(definition.get("template"))
    # A custom entry already has its own saved filters; every other source
    # only has them once a run has discovered them (see analysis_engine).
    if definition.get("chain"):
        merged["filters"] = analysis_filters.options(
            _level_scope(session, definition), _level_filter_defs(session.session_id, session),
        )
    else:
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
            "guided_proposals": result.guided_proposals,
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
def get_repository(session_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryResponse:
    session = deps.load_owned_session(session_id, user)
    definitions = analysis_repository.get_repository(session_id)
    return AnalysisRepositoryResponse(
        session_id=session_id, entries=[_merge_entry(session, d) for d in definitions]
    )


@router.post("/repository/{session_id}/draft", response_model=AnalysisDraft)
def draft_analysis(session_id: str, body: DraftAnalysisRequest, user: User = Depends(get_user)) -> AnalysisDraft:
    """Turns the PM's description into reviewable computation logic, a
    template match (or code generation), a chart recommendation and
    filters. Nothing is saved -- the PM confirms via /custom."""
    session = deps.load_owned_session(session_id, user)
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
def add_custom_analysis(session_id: str, body: AddCustomAnalysisRequest, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    session = deps.load_owned_session(session_id, user)
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
    log_event(session_id, user.id, "analysis_custom_added", {"entry_id": entry["id"], "name": entry.get("name")})
    return _merge_entry(session, entry)


@router.post("/repository/{session_id}/suggest", response_model=SuggestAnalysisEntriesResponse)
def suggest_analyses(session_id: str, user: User = Depends(get_user)) -> SuggestAnalysisEntriesResponse:
    session = deps.load_owned_session(session_id, user)
    try:
        suggestions = analysis_suggester.suggest_analyses(
            session.df, analysis_repository.get_repository(session_id), feature_repository.get_approved_entries(session_id),
        )
    except Exception as exc:
        logger.exception("Analysis suggestion agent failed for session %s", session_id)
        raise HTTPException(
            status_code=502, detail="Analysis suggestion agent is unavailable right now. Please try again."
        ) from exc
    new_entries = analysis_repository.add_ai_suggested_entries(session_id, suggestions)
    log_event(session_id, user.id, "analysis_suggested", {"count": len(new_entries)})
    return SuggestAnalysisEntriesResponse(session_id=session_id, entries=[_merge_entry(session, e) for e in new_entries])


@router.post("/repository/{session_id}/entries/{entry_id}/accept", response_model=AnalysisRepositoryEntry)
def accept_entry(session_id: str, entry_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.set_entry_status(session_id, entry_id, "approved")
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    log_event(session_id, user.id, "analysis_accepted", {"entry_id": entry_id, "name": entry.get("name")})
    return _merge_entry(session, entry)


@router.post("/repository/{session_id}/entries/{entry_id}/reject", response_model=AnalysisRepositoryEntry)
def reject_entry(session_id: str, entry_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.set_entry_status(session_id, entry_id, "rejected")
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    log_event(session_id, user.id, "analysis_rejected", {"entry_id": entry_id, "name": entry.get("name")})
    return _merge_entry(session, entry)


def _run_entry(session: AuditSession, session_id: str, entry: dict) -> AnalysisRepositoryEntry:
    """Runs the Analysis Agent for one entry and stores the result on the
    session, in-memory. Never raises on an agent-side failure -- that's
    recorded as run_status="error" so one entry's failure never blocks the
    rest of the page, mirroring the feature system's skipped_notes
    philosophy."""
    computation = analysis_engine.run_analysis(
        session_id, analysis_dependencies.prepare_entry(session_id, entry, session.df), session.df,
    )
    session.analysis_results[entry["id"]] = _to_result(entry, computation)
    return _merge_entry(session, entry)  # callers save the session once they are done


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
def run_entry(session_id: str, entry_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    if entry["status"] == "rejected":
        raise HTTPException(status_code=422, detail="This analysis was rejected and can't be run.")
    # Required features must be selected (approved) and computed first --
    # enforced here, not only by the UI.
    blocked = analysis_dependencies.block_message(analysis_dependencies.resolve(session_id, entry, session.df))
    if blocked:
        raise HTTPException(status_code=422, detail=blocked)
    out = _run_entry(session, session_id, entry)
    store.save(session)
    log_event(session_id, user.id, "analysis_run", {"entry_id": entry_id, "name": entry.get("name"), "run_status": out.run_status})
    return out


@router.post("/repository/{session_id}/entries/{entry_id}/required-features/select", response_model=AnalysisRepositoryEntry)
def select_required_feature(session_id: str, entry_id: str, body: SelectRequiredFeatureRequest, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    """Approves one of the features this analysis requires. It still has to be
    computed (the Features step) before the analysis can run."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    wanted = {r.get("feature_id") for r in analysis_dependencies.resolve(session_id, entry, session.df)}
    if body.feature_id not in wanted:
        raise HTTPException(status_code=404, detail="That feature is not a requirement of this analysis.")
    if not analysis_dependencies.select_feature(session_id, body.feature_id):
        raise HTTPException(status_code=422, detail="This feature can't be selected.")
    return _merge_entry(session, analysis_repository.get_entry(session_id, entry_id))


@router.post("/repository/{session_id}/entries/{entry_id}/filter", response_model=AnalysisRepositoryEntry)
def filter_entry(session_id: str, entry_id: str, body: FilterAnalysisRequest, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    """A filtered VIEW of an already-run analysis, for its chart's filter
    controls. Never calls an LLM and never replaces the stored (unfiltered)
    result -- the report and the repository always use the unfiltered run.
    The interpretation and drilldowns shown are the unfiltered run's."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Analysis entry not found in this session's repository.")
    base = session.analysis_results.get(entry_id)
    if base is None or base.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before filtering it.")

    if entry.get("chain"):
        entry = {**entry, "filters": _level_filter_defs(session_id, session)}
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
    merged.update(view.model_dump(exclude={"id", "chart_recommendation", "template", "filters"}))
    merged["applied_filters"] = applied
    return AnalysisRepositoryEntry(**merged)


@router.post("/repository/{session_id}/entries/{entry_id}/drilldowns/{drilldown_id}/trigger", response_model=AnalysisRepositoryEntry)
def trigger_drilldown(session_id: str, entry_id: str, drilldown_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    session = deps.load_owned_session(session_id, user)
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
    session.analysis_results[entry_id] = parent_result  # changed in place above: re-assign so it is saved

    out = _run_entry(session, session_id, child_entry)
    store.save(session)
    log_event(session_id, user.id, "drilldown_run", {"parent_entry_id": entry_id, "entry_id": child_entry["id"], "name": child_entry.get("name")})
    return out


@router.post("/repository/{session_id}/entries/{entry_id}/drilldowns/suggest-more", response_model=AnalysisRepositoryEntry)
def suggest_more_drilldowns(session_id: str, entry_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    """Asks the Analysis Agent for up to 3 more follow-ups, different from the
    ones this analysis already has, and appends them to its suggestions."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    result = session.analysis_results.get(entry_id)
    if entry is None or result is None or result.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before asking for more drill-downs.")

    existing = result.drilldown_suggestions
    try:
        fresh = analysis_agent.suggest_drilldowns(
            analysis_dependencies.prepare_entry(session_id, entry, session.df),
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
    session.analysis_results[entry_id] = result  # list extended in place: re-assign so it is saved
    store.save(session)
    return _merge_entry(session, entry)


# --- Guided drill-down chains ---------------------------------------------------


def _result_labels(result: AnalysisResult | None) -> list[str]:
    """The groups a finished level shows (its label column), in table order."""
    if result is None or not result.result_table or not result.result_columns:
        return []
    col = result.result_columns[0]
    return [str(r[col]) for r in result.result_table if r.get(col) is not None]


def _chain_dims(chain: dict) -> list[str]:
    """Every X-axis column of a chain level (older levels only stored `dimension`)."""
    return list(chain.get("dimensions") or [chain["dimension"]])


def _pinned(entry: dict, dimension: str, where: list[dict]) -> set[str]:
    """Columns a next drill-down can no longer use as an X axis: the ones this
    level already shows or filters on."""
    dims = set(_chain_dims(entry["chain"])) if entry.get("chain") else set()
    return {dimension} | dims | {w["column"] for w in where}


def _feature_columns(session_id: str, session: AuditSession) -> list[str]:
    return [f["output_column"] for f in analysis_dependencies.available_features(session_id, session.df)]


def _level_of(entry: dict) -> int:
    return (entry.get("chain") or {}).get("level", 1)


def _focus_label(values: list[str]) -> str:
    return ", ".join(values) if len(values) <= 2 else f"{values[0]}, {values[1]} +{len(values) - 2}"


def _parent_scope(session: AuditSession, parent: dict) -> tuple[str | None, list[dict]]:
    """(the dimension the parent groups by, the row filter it already applies)."""
    result = session.analysis_results.get(parent["id"])
    if parent.get("chain"):
        return parent["chain"]["dimension"], list(parent["chain"].get("where") or [])
    template = parent.get("template") or (result.template if result else None) or {}
    dimension = analysis_drilldown.root_dimension(parent, result.template if result else None,
                                                  result.result_columns if result else None, session.df)
    return dimension, [w for w in template.get("where", [])]


@router.get("/repository/{session_id}/entries/{entry_id}/drilldown/options", response_model=DrilldownOptions)
def drilldown_options(session_id: str, entry_id: str, user: User = Depends(get_user)) -> DrilldownOptions:
    """What a guided drill-down from this analysis can look like: for a
    level-1 analysis, which values are 'wide' (span many child groups);
    for a chain level, its own top/bottom groups as the default focus."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    result = session.analysis_results.get(entry_id)
    if entry is None or result is None or result.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before drilling into it.")

    level = _level_of(entry)
    base = dict(entry_id=entry_id, level=level, max_level=analysis_drilldown.MAX_CHAIN_LEVEL,
                metrics=analysis_drilldown.available_metrics(session.df))
    if level >= analysis_drilldown.MAX_CHAIN_LEVEL:
        return DrilldownOptions(**base, can_drill=False, reason=f"Drill-downs stop at level {analysis_drilldown.MAX_CHAIN_LEVEL}.")

    dimension, where = _parent_scope(session, entry)
    if dimension is None:
        return DrilldownOptions(**base, can_drill=False, reason="This analysis isn't grouped by a single column, so there is nothing to drill into.")
    pinned = _pinned(entry, dimension, where)
    candidates = analysis_drilldown_agent.candidate_dimensions(session.df, pinned, _feature_columns(session_id, session))
    child = analysis_drilldown.next_dimension(dimension, session.df)
    if child not in candidates:
        child = candidates[0] if candidates else None
    if child is None:
        return DrilldownOptions(**base, can_drill=False, focus_dimension=dimension,
                                reason="There is no other column left to break this down by.")

    options, default_focus = _focus_pool(session, entry, result, dimension, where, child)
    next_where = where + ([analysis_drilldown.focus_condition(dimension, default_focus)] if default_focus else [])
    return DrilldownOptions(
        **base, can_drill=bool(options), focus_dimension=dimension, child_dimension=child,
        candidate_dimensions=candidates, numeric_columns=analysis_drilldown.numeric_columns(session.df),
        focus_options=options, default_focus=default_focus,
        default_rank=DrilldownRank(**analysis_drilldown.default_rank_for(session.df, next_where, child)),
    )


def _focus_pool(session: AuditSession, entry: dict, result: AnalysisResult, dimension: str, where: list[dict], child: str) -> tuple[list[dict], list[str]]:
    """The values the PM can focus on. A chain level offers the groups it shows
    (all selected by default); a level-1 analysis offers the biggest values,
    with the widest one selected."""
    scoped = analysis_drilldown._apply(session.df, where)
    if entry.get("chain"):
        labels = _result_labels(result)
        col = analysis_drilldown.as_labels(scoped[dimension])
        options = [
            {"value": v, "rows": int((col == v).sum()),
             "child_count": int(scoped[col == v][child].nunique()), "is_wide": False}
            for v in labels
        ]
        return options, labels
    options = analysis_drilldown.focus_options(scoped, dimension, child)
    wide = [o["value"] for o in options if o["is_wide"]]
    return options, (wide[:1] or [o["value"] for o in options[:1]])


@router.post("/repository/{session_id}/entries/{entry_id}/drilldown/propose", response_model=list[DrilldownProposal])
def propose_drilldowns(session_id: str, entry_id: str, more: bool = False, user: User = Depends(get_user)) -> list[DrilldownProposal]:
    """10-15 AI-suggested next drill-downs (dimension, focus, top/bottom N,
    metric), validated against the data -- generated once and cached on the
    entry's result; every later call (opening this entry again) returns the
    same cached list with no LLM cost. Passing `more=true` (the single
    "Suggest with AI" button, once a batch already exists) asks for an
    additional batch that can't repeat what's cached, and appends it."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    result = session.analysis_results.get(entry_id)
    if entry is None or result is None or result.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before drilling into it.")
    cached = [p.model_dump() for p in result.guided_proposals]
    if cached and not more:
        return result.guided_proposals
    if _level_of(entry) >= analysis_drilldown.MAX_CHAIN_LEVEL:
        return result.guided_proposals
    dimension, where = _parent_scope(session, entry)
    if dimension is None:
        return result.guided_proposals
    pinned = _pinned(entry, dimension, where)
    features = _feature_columns(session_id, session)
    pool_child = analysis_drilldown_agent.candidate_dimensions(session.df, pinned, features)
    if not pool_child:
        return result.guided_proposals
    options, _ = _focus_pool(session, entry, result, dimension, where, pool_child[0])
    new_proposals = analysis_drilldown_agent.propose(
        session.df, entry, dimension, where, [o["value"] for o in options],
        result.result_table or [], result.interpretation, avoid=cached or None,
        feature_columns=features, pinned=pinned,
    )
    result.guided_proposals = result.guided_proposals + [DrilldownProposal(**p) for p in new_proposals]
    session.analysis_results[entry_id] = result
    store.save(session)
    return result.guided_proposals


def _build_level(
    session: AuditSession, dimensions: list[str] | str, metric: str, rank: dict, where: list[dict],
    metric_column: str | None = None,
) -> tuple[dict, str]:
    try:
        return analysis_drilldown.build_template(dimensions, metric, rank, where, session.df, metric_column)
    except analysis_templates.TemplateError as exc:
        raise HTTPException(status_code=422, detail=f"Can't build this drill-down: {exc}") from exc


def _mark_stale(session_id: str, entry_id: str) -> None:
    entries = analysis_repository.get_repository(session_id)
    for d in analysis_drilldown.descendants(entries, entry_id):
        analysis_repository.update_entry(session_id, d["id"], {"chain": {**d["chain"], "stale": True}})


@router.post("/repository/{session_id}/entries/{entry_id}/drilldown", response_model=AnalysisRepositoryEntry)
def confirm_drilldown(session_id: str, entry_id: str, body: ConfirmDrilldownRequest, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    """The PM's Confirm: builds and runs the next chain level for the chosen
    focus (e.g. Product = Table Grapes -> its top 3 Origins)."""
    session = deps.load_owned_session(session_id, user)
    parent = analysis_repository.get_entry(session_id, entry_id)
    result = session.analysis_results.get(entry_id)
    if parent is None or result is None or result.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before drilling into it.")
    level = _level_of(parent) + 1
    if level > analysis_drilldown.MAX_CHAIN_LEVEL:
        raise HTTPException(status_code=422, detail=f"Drill-downs stop at level {analysis_drilldown.MAX_CHAIN_LEVEL}.")

    dimension, where = _parent_scope(session, parent)
    default_child = analysis_drilldown.next_dimension(dimension, session.df) if dimension else None
    children = list(dict.fromkeys(body.child_dimensions or [body.child_dimension or default_child]))
    pinned = _pinned(parent, dimension, where) if dimension else set()
    if dimension is None or not children or any(c is None or c not in session.df.columns or c in pinned for c in children):
        raise HTTPException(status_code=422, detail="Couldn't work out which level to drill into.")
    if len(children) > 5:
        raise HTTPException(status_code=422, detail="Pick at most 5 X-axis columns.")
    if body.metric in analysis_drilldown.AGG_LABELS and (not body.metric_column or body.metric_column not in analysis_drilldown.numeric_columns(session.df)):
        raise HTTPException(status_code=422, detail="Pick a numeric column to average.")
    if body.metric == "pct_in_spec" and analysis_drilldown.find_in_spec_column(session.df) is None:
        raise HTTPException(status_code=422, detail="No '% in spec' column exists yet -- compute that feature first.")

    values = list(dict.fromkeys(v for v in body.focus_values if v))
    rank = body.rank.model_dump()
    common = dict(session=session, session_id=session_id, parent=parent, dimension=dimension, where=where,
                  children=children, metric=body.metric, metric_column=body.metric_column, rank=rank, level=level)

    if body.split and len(values) > 1:
        if len(values) > MAX_SPLIT_SLIDES:
            raise HTTPException(status_code=422, detail=f"Pick at most {MAX_SPLIT_SLIDES} values to get one slide each.")
        # Entries are created one at a time (they share one file); the runs -- an
        # LLM interpretation each -- then happen concurrently.
        created = [_create_level(values=[v], split=True, **common) for v in values]
        todo = [entry for entry, is_new in created if is_new]
        with ThreadPoolExecutor(max_workers=3) as pool:
            # one wrapped callable PER job: workers must see this request's user/session (token + audit attribution)
            for fut in [pool.submit(request_context.wrap(_run_entry), session, session_id, e) for e in todo]:
                fut.result()
        store.save(session)
        for e in todo:
            log_event(session_id, user.id, "drilldown_run", {"parent_entry_id": entry_id, "entry_id": e["id"], "name": e.get("name")})
        return _merge_entry(session, created[0][0])

    entry, is_new = _create_level(values=values, split=False, **common)
    if not is_new:
        return _merge_entry(session, entry)
    out = _run_entry(session, session_id, entry)
    store.save(session)
    log_event(session_id, user.id, "drilldown_run", {"parent_entry_id": entry_id, "entry_id": entry["id"], "name": entry.get("name")})
    return out


def _create_level(
    *, session: AuditSession, session_id: str, parent: dict, dimension: str, where: list[dict], children: list[str],
    metric: str, metric_column: str | None, rank: dict, level: int, values: list[str], split: bool,
    status: str = "approved",
) -> tuple[dict, bool]:
    """Creates one chain level for `values` (not yet run), or returns the
    identical level if it already exists. Returns (entry, was_created)."""
    new_where = where + [analysis_drilldown.focus_condition(dimension, values)]
    child = children[0]
    template, chart_type = _build_level(session, children, metric, rank, new_where, metric_column)
    label = _focus_label(values)
    chain = {
        "chain_id": (parent.get("chain") or {}).get("chain_id") or f"chain_{parent['id']}",
        "level": level, "dimension": child, "dimensions": children, "metric": metric, "metric_column": metric_column,
        "rank": rank, "where": new_where,
        "focus_dimension": dimension, "focus_values": values, "focus_label": label, "split": split, "stale": False,
    }
    for existing in analysis_repository.get_repository(session_id):
        c = existing.get("chain")
        # Only an accepted level is reused: a pending or rejected one belongs to a suggested path.
        if (existing.get("status") == "approved" and existing.get("parent_id") == parent["id"] and c
                and c["where"] == new_where and _chain_dims(c) == children):
            return existing, False

    filters = _level_filter_defs(session_id, session)
    name = analysis_drilldown.level_name(children, rank, label, metric, metric_column)
    entry = analysis_repository.add_chain_entry(
        session_id, parent["id"], name=name, description=f"{name} (drill-down from {parent['name']}).",
        template=template, chart_type=chart_type, filters=filters, chain=chain, status=status,
    )
    return entry, True


@router.post("/repository/{session_id}/entries/{entry_id}/drilldown/rank", response_model=AnalysisRepositoryEntry)
def rerank_drilldown(session_id: str, entry_id: str, body: DrilldownRank, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    """Changes a level's Top/Bottom and N (or what it ranks by). Re-runs just
    this level and marks every level below it stale, so the report never
    changes unnoticed."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None or not entry.get("chain"):
        raise HTTPException(status_code=404, detail="That isn't a drill-down level.")
    chain = entry["chain"]
    if body.by == "pct_in_spec" and analysis_drilldown.find_in_spec_column(session.df) is None:
        raise HTTPException(status_code=422, detail="No '% in spec' column exists yet -- compute that feature first.")
    rank = body.model_dump()
    template, chart_type = _build_level(session, _chain_dims(chain), chain["metric"], rank, chain["where"], chain.get("metric_column"))
    name = analysis_drilldown.level_name(_chain_dims(chain), rank, chain["focus_label"], chain["metric"], chain.get("metric_column"))
    updated = analysis_repository.update_entry(session_id, entry_id, {
        "template": template, "name": name, "chain": {**chain, "rank": rank, "stale": False},
        "chart_recommendation": {"chart_type": chart_type, "reason": "Chosen for this drill-down level.", "alternatives": []},
    })
    _mark_stale(session_id, entry_id)
    out = _run_entry(session, session_id, updated)
    store.save(session)
    log_event(session_id, user.id, "drilldown_run", {"entry_id": entry_id, "name": (updated or {}).get("name")})
    return out


@router.post("/repository/{session_id}/entries/{entry_id}/drilldown/refresh", response_model=AnalysisRepositoryEntry)
def refresh_drilldown(session_id: str, entry_id: str, user: User = Depends(get_user)) -> AnalysisRepositoryEntry:
    """Rebuilds a stale level from its parent's CURRENT groups (e.g. the
    parent is now top 2 origins, so this level covers just those 2)."""
    session = deps.load_owned_session(session_id, user)
    entry = analysis_repository.get_entry(session_id, entry_id)
    if entry is None or not entry.get("chain"):
        raise HTTPException(status_code=404, detail="That isn't a drill-down level.")
    parent = analysis_repository.get_entry(session_id, entry["parent_id"])
    chain = entry["chain"]
    if parent is not None and parent.get("chain") and chain.get("split"):
        # A "one slide per value" sibling keeps its own single focus; it only
        # needs the value to still be one of the parent's groups.
        labels = _result_labels(session.analysis_results.get(parent["id"]))
        if not labels:
            raise HTTPException(status_code=409, detail="Run the level above first.")
        if not set(chain["focus_values"]) <= set(labels):
            raise HTTPException(
                status_code=409,
                detail=f"{chain['focus_label']} is no longer one of the level above's groups. Restore that level's rank, or drill down again.",
            )
    elif parent is not None and parent.get("chain"):
        labels = _result_labels(session.analysis_results.get(parent["id"]))
        if not labels:
            raise HTTPException(status_code=409, detail="Run the level above first.")
        parent_dim, parent_where = _parent_scope(session, parent)
        where = parent_where + [analysis_drilldown.focus_condition(parent_dim, labels)]
        chain = {**chain, "where": where, "focus_values": labels, "focus_label": _focus_label(labels)}
    template, chart_type = _build_level(session, _chain_dims(chain), chain["metric"], chain["rank"], chain["where"], chain.get("metric_column"))
    name = analysis_drilldown.level_name(_chain_dims(chain), chain["rank"], chain["focus_label"], chain["metric"], chain.get("metric_column"))
    updated = analysis_repository.update_entry(session_id, entry_id, {
        "template": template, "name": name, "chain": {**chain, "stale": False},
        "chart_recommendation": {"chart_type": chart_type, "reason": "Chosen for this drill-down level.", "alternatives": []},
    })
    _mark_stale(session_id, entry_id)
    out = _run_entry(session, session_id, updated)
    store.save(session)
    log_event(session_id, user.id, "drilldown_run", {"entry_id": entry_id, "name": (updated or {}).get("name")})
    return out


@router.get("/{session_id}/overall", response_model=OverallAnalysisReport)
def get_overall_analysis(session_id: str, user: User = Depends(get_user)) -> OverallAnalysisReport:
    session = deps.load_owned_session(session_id, user)
    definitions = analysis_repository.get_repository(session_id)
    done_entries = [
        _merge_entry(session, d).model_dump()
        for d in definitions
        if d.get("status") == "approved"
        and session.analysis_results.get(d["id"], None) and session.analysis_results[d["id"]].run_status == "done"
    ]
    highlights = overall_analysis.build_highlights(len(session.df), session.features, done_entries)
    try:
        narrative = overall_analysis_agent.generate_narrative(len(session.df), highlights)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Overall analysis narrative agent (Bedrock) is unavailable: {exc}"
        ) from exc
    report = OverallAnalysisReport(
        session_id=session_id, row_count=len(session.df), highlights=highlights, narrative=narrative
    )
    session.overall_analysis = report
    store.save(session)
    return report
