import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    ClientBriefFeatureRequest,
    ClientBriefFeatureResponse,
    ClientRequirement,
    FeatureDefinitionsSummary,
    FeatureReport,
    FeatureSuggestion,
    FeatureSuggestionsResponse,
    KpiFeatureOutcome,
    KpiStoreEntry,
    KpiStoreListResponse,
    RequestFeatureRequest,
    SaveDefinitionRequest,
    SavedDefinition,
    SavedDefinitionsResponse,
    SetSavedScopeRequest,
    SuggestFeaturesRequest,
)
from app.services import custom_library_store, feature_engineering, feature_orchestrator, kpi_store
from app.services import feature_definitions_store as defs_store
from app.services import feature_request_agent, feature_suggester
from app.services.audit_store import store as audit_store

router = APIRouter(prefix="/api/features", tags=["features"])


@router.post("/definitions", response_model=FeatureDefinitionsSummary)
async def upload_feature_definitions(file: UploadFile = File(...)) -> FeatureDefinitionsSummary:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        features = defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or "customer_kpi_profile.json"
    defs_store.store.set(filename, features)

    return FeatureDefinitionsSummary(
        filename=filename,
        feature_count=len(features),
        feature_names=[f["name"] for f in features],
    )


@router.get("/definitions", response_model=FeatureDefinitionsSummary)
def get_feature_definitions() -> FeatureDefinitionsSummary:
    if defs_store.store.definitions is None:
        raise HTTPException(status_code=404, detail="No Customer KPI Profile has been uploaded yet.")
    return FeatureDefinitionsSummary(
        filename=defs_store.store.filename,
        feature_count=len(defs_store.store.definitions),
        feature_names=[f["name"] for f in defs_store.store.definitions],
    )


@router.post("/suggest", response_model=FeatureSuggestionsResponse)
def suggest_features(body: SuggestFeaturesRequest) -> FeatureSuggestionsResponse:
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df
    try:
        suggestions = feature_suggester.suggest_features(base_df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature suggestion agent (Groq) is unavailable: {exc}") from exc
    return FeatureSuggestionsResponse(session_id=body.session_id, suggestions=suggestions)


@router.post("/request", response_model=FeatureSuggestion)
def request_feature(body: RequestFeatureRequest) -> FeatureSuggestion:
    """Step 2's "User Requests a Feature" entry point: a plain-language ask
    (e.g. "flag if the unit was swapped mid-trip"), turned into a ready-to-
    apply spec by feature_request_agent.py -- one of the three deterministic
    templates when it fits, otherwise `ai_generated` (a calculation_prompt
    for the same sandboxed pandas-snippet path AI-suggested features already
    use). Returned shaped exactly like a FeatureSuggestion so the frontend
    applies it via the existing POST /api/audit/{session_id}/features
    (extra_features) and saves it via POST /api/features/custom-features,
    with no new execution or storage code needed for either step -- this
    endpoint's contract and the frontend flow around it are unchanged.

    Two additions behind that same contract (source: USER_REQUESTED, see
    kpi_store.py): before drafting, check whether an equivalent feature is
    already in the KPI Store and hand that back instead of asking the
    Feature Agent again; after a fresh draft validates against this data,
    register it in the KPI Store so it's found this way next time."""
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df

    existing = kpi_store.store.find_equivalent(body.request_text, body.request_text)
    if existing:
        return FeatureSuggestion(**existing["spec"])

    try:
        suggestion = feature_request_agent.draft_feature_spec(body.request_text, base_df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature request agent (Groq) is unavailable: {exc}") from exc

    spec = suggestion.model_dump(exclude_none=True)
    _new_df, results, _skipped = feature_engineering.apply_features(base_df, [spec])
    if results:
        source_cols = feature_orchestrator.spec_source_columns(spec, list(base_df.columns))
        kpi_store.store.upsert(
            name=suggestion.name,
            description=suggestion.description,
            source="USER_REQUESTED",
            output_column=suggestion.output_column,
            spec_type=suggestion.type,
            formula=spec.get("formula", ""),
            python_code=spec.get("generated_code"),
            data_type=feature_orchestrator.infer_data_type(_new_df[suggestion.output_column]),
            dependencies=feature_orchestrator.dependency_ids(source_cols, set(base_df.columns.astype(str))),
            source_columns=source_cols,
            spec=spec,
        )
    return suggestion


@router.post("/client-brief", response_model=ClientBriefFeatureResponse)
def submit_client_brief(body: ClientBriefFeatureRequest) -> ClientBriefFeatureResponse:
    """Feature Engineering's main entry point (sections 1-3, 7, 9, 11-12 of
    the spec): structured requirements -> explicit-client + AI-suggested
    features -> created or reused via the Feature Agent -> registered in
    the KPI Store. See feature_orchestrator.py for the full pipeline; this
    endpoint just wires it to the session and recomputes the Features
    page's report so the result shows up immediately, the same way
    accepting an AI suggestion already does.

    `body.planned_features` is the normal path now -- the Planner Agent
    (orchestrator_agent.py) already decided this list once, up front, and
    the caller (FeaturesPage) is just handing it over rather than asking
    this endpoint to re-derive it from `body.brief`. Extraction only runs
    here as a fallback when planned_features is omitted (a direct API
    caller, tests)."""
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df

    if body.planned_features is not None:
        client_requirements = [
            {"feature_name": f.feature_name, "description": f.description, "type": "derived_feature", "source": "CLIENT_REQUESTED"}
            for f in body.planned_features
        ]
    else:
        try:
            client_requirements = feature_orchestrator.extract_client_requirements(body.brief, base_df)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Client brief agent (Groq) is unavailable: {exc}") from exc
    if not client_requirements:
        # Nothing feature-shaped in this brief -- an entirely normal outcome
        # now that every Client Brief always passes through here first (the
        # Planner Agent plans for BOTH Feature Engineering and Analysis, not
        # one or the other -- see UploadPage/AuditPage). A pure "what does
        # the data show" question just has nothing for this endpoint to do;
        # the SAME plan's `analyses` half continues on to Analysis right
        # after (see FeaturesPage's prefillClientBrief effect), which is
        # where it actually gets resolved. Not a failure.
        return ClientBriefFeatureResponse(
            session_id=body.session_id,
            client_requirements=[],
            ai_suggested=[],
            outcomes=[],
            accepted_specs=[],
            feature_report=FeatureReport(
                session_id=session.session_id,
                row_count=len(session.df),
                column_count=len(session.df.columns),
                columns=[str(c) for c in session.df.columns],
                features=session.features,
                skipped_notes=session.feature_skipped_notes,
                excluded_feature_ids=session.excluded_feature_ids,
            ),
        )

    # AI-suggested extras (features beyond what was explicitly asked for)
    # only make sense for the OLD self-extraction path -- when the Planner
    # Agent already ran (planned_features given), the user already reviewed
    # and approved an exact list on the Recommendation page; layering in
    # more here would create features nobody approved. `create_or_reuse_
    # features` still needs a `source` per item, so ai_suggested just stays
    # an empty list rather than skipping the call.
    ai_suggested: list[dict] = [] if body.planned_features is not None else feature_orchestrator.suggest_additional_features(
        body.brief, client_requirements, base_df
    )

    outcomes, accepted_specs, _working = feature_orchestrator.create_or_reuse_features(
        client_requirements + ai_suggested, base_df
    )

    # Persist everything this brief just resolved into the session's own
    # running "extra features" list (same field apply_features/{id}/features
    # reads and writes) -- by id, so a spec this brief reuses/re-creates
    # replaces its own prior entry rather than duplicating, and anything
    # accepted earlier (an AI suggestion, another brief) survives alongside
    # it instead of being silently dropped. Without this, a later bare
    # recompute (a fresh page load included) would have no way to know this
    # brief's features should still be there.
    by_id = {d.get("id"): d for d in session.extra_feature_defs}
    for spec in accepted_specs:
        d = spec.model_dump(exclude_none=True)
        by_id[d["id"]] = d
    session.extra_feature_defs = list(by_id.values())

    # Recompute the session's feature report with everything layered on top
    # of the usual profile + saved "regular" KPIs -- the exact same recompute
    # the rest of the Features page already uses.
    if session.pre_feature_df is None:
        session.pre_feature_df = session.df.copy()
    combined_defs = custom_library_store.merge_definitions(
        list(defs_store.store.definitions or []),
        custom_library_store.store.regular_specs("features"),
        session.extra_feature_defs,
    )
    if session.excluded_feature_ids:
        excluded = set(session.excluded_feature_ids)
        combined_defs = [d for d in combined_defs if d.get("id") not in excluded]
    new_df, results, skipped_notes = feature_engineering.apply_features(session.pre_feature_df, combined_defs)
    session.df = new_df
    session.features = results
    session.feature_skipped_notes = skipped_notes

    feature_report = FeatureReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        features=session.features,
        skipped_notes=session.feature_skipped_notes,
        excluded_feature_ids=session.excluded_feature_ids,
    )

    return ClientBriefFeatureResponse(
        session_id=body.session_id,
        client_requirements=[ClientRequirement(**r) for r in client_requirements],
        ai_suggested=[ClientRequirement(**r) for r in ai_suggested],
        outcomes=[KpiFeatureOutcome(**o.__dict__) for o in outcomes],
        accepted_specs=accepted_specs,
        feature_report=feature_report,
    )


@router.get("/kpi-store", response_model=KpiStoreListResponse)
def list_kpi_store() -> KpiStoreListResponse:
    """Transparency endpoint over the central registry (section 8) -- every
    feature ever created or reused via the Client Brief / user-request
    pipeline, with its provenance, formula, and version."""
    return KpiStoreListResponse(features=[KpiStoreEntry(**entry) for entry in kpi_store.store.all()])


@router.get("/custom-features", response_model=SavedDefinitionsResponse)
def list_saved_features() -> SavedDefinitionsResponse:
    """Every custom KPI the user has saved, of either scope -- the Features
    page shows the "suggested" ones alongside the AI suggestions, and marks
    the "regular" ones as already part of every run."""
    return SavedDefinitionsResponse(
        items=[SavedDefinition(**item) for item in custom_library_store.store.entries("features")]
    )


@router.post("/custom-features", response_model=SavedDefinition)
def save_custom_feature(body: SaveDefinitionRequest) -> SavedDefinition:
    """Persists one custom KPI to disk. `scope` is the user's choice between
    the two save options: "regular" (merged into every future run
    automatically) or "suggested" (kept in their list, added when they want
    it). Upserts by the definition's own id."""
    try:
        entry = custom_library_store.store.save("features", body.definition, body.scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SavedDefinition(**entry)


@router.post("/custom-features/{definition_id}/scope", response_model=SavedDefinition)
def set_saved_feature_scope(definition_id: str, body: SetSavedScopeRequest) -> SavedDefinition:
    try:
        entry = custom_library_store.store.set_scope("features", definition_id, body.scope)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No saved KPI with that id.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SavedDefinition(**entry)


@router.delete("/custom-features/{definition_id}", response_model=SavedDefinitionsResponse)
def delete_saved_feature(definition_id: str) -> SavedDefinitionsResponse:
    """Removes it from the library only. A KPI already computed for a
    running session stays there until that session recomputes."""
    try:
        custom_library_store.store.delete("features", definition_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No saved KPI with that id.") from exc
    return SavedDefinitionsResponse(
        items=[SavedDefinition(**item) for item in custom_library_store.store.entries("features")]
    )
