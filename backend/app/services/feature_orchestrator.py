"""Client Brief -> Feature Requirements -> Feature Agent -> Feature Creation
-> KPI Store. This module is the orchestration layer described in the
Feature Engineering spec; it does not introduce a second execution engine --
every piece it touches already exists:

  1. `extract_client_requirements` -- Groq reads the brief and returns
     structured JSON: one entry per NEW column/KPI the client explicitly
     asked for (section 1). This is the "natural language -> structured
     JSON" step; nothing downstream reads free text again.
  2. `suggest_additional_features` -- same idea, but asks Groq for a few
     EXTRA features that would help satisfy the same brief (section 3),
     given what's already planned so it doesn't just restate the explicit
     list.
  3. `create_or_reuse_features` -- for every requirement (explicit ones
     first, so they always get first claim on being "the" definition of a
     name -- section 11's priority order), checks kpi_store.py for an
     equivalent feature (section 9) and reuses it, or hands the requirement
     to feature_request_agent.draft_feature_spec (the SAME Feature Agent
     behind today's "User Requests a Feature" box) and executes the result
     through feature_engineering.apply_features (the SAME sandboxed
     execution engine every feature in this app already runs through).
     Successful creations are persisted to kpi_store.py with their source
     provenance.

Dependency ordering (section 7) is a worklist, not an explicit graph: each
pass tries every still-unresolved requirement against the dataframe as it
stands after everything resolved so far in this call. A requirement that
needs a column another requirement will create just fails this pass (or
fails to even draft, if it's a template type -- the Feature Agent validates
referenced columns eagerly) and is retried next pass, once that column
exists. The loop stops when a full pass makes no further progress.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from app.schemas import FeatureSuggestion
from app.services import feature_engineering, feature_request_agent, kpi_store
from app.services.groq_client import chat_json

MAX_PASSES = 6

CLIENT_BRIEF_SYSTEM_PROMPT = """You read a client's plain-language brief for \
a cold-chain shipment analytics tool and extract every DISTINCT engineered \
feature/column/KPI the client is explicitly asking for -- a NEW calculated \
column, not a question about the data as it already stands and not an \
analysis/chart/report request.

You'll be given the brief plus the current column names, dtypes, and a few \
sample values per column. Extract one entry per distinct feature. Use a \
short snake_case name for each (e.g. "transit_duration",
"temperature_excursion_duration"). If the brief doesn't actually ask for any \
new column (it's only a question, or only asks for analysis/a chart/a \
report), return an empty list -- do not invent a feature.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"client_requirements": [
  {"feature_name": "short_snake_case_name",
   "description": "one plain-English sentence restating exactly what to compute"}
]}"""

AI_SUGGEST_SYSTEM_PROMPT = """You are a data engineer for a cold-chain \
shipment analytics tool. A client brief has already been read, and the \
features it explicitly asked for are listed below (already planned -- do \
NOT repeat or lightly reword any of them). Suggest up to 3 ADDITIONAL \
engineered features/columns that would genuinely help satisfy the same \
brief -- supporting context or a natural companion metric, not a duplicate.

You'll be given the brief, the already-planned features, and the current \
column names/dtypes/samples. If nothing additional would genuinely help, \
return an empty list.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"ai_suggested": [
  {"feature_name": "short_snake_case_name",
   "description": "one plain-English sentence on what to compute and why it helps"}
]}"""


@dataclass
class RequirementOutcome:
    feature_name: str
    description: str
    source: str
    status: str  # "reused" | "created" | "failed"
    kpi_id: str | None = None
    output_column: str | None = None
    error: str | None = None


def _columns_block(df: pd.DataFrame) -> str:
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(3).tolist()
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)


def _parse_requirement_items(raw: str, key: str) -> list[dict]:
    payload = json.loads(raw)
    items = payload.get(key, [])
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, dict) and item.get("feature_name") and item.get("description"):
            out.append({
                "feature_name": str(item["feature_name"]).strip(),
                "description": str(item["description"]).strip(),
            })
    return out


def extract_client_requirements(brief: str, df: pd.DataFrame) -> list[dict]:
    """Section 1: natural-language brief -> structured JSON. Raises whatever
    the Groq client raises (missing key, network error) -- the router turns
    that into a 502, same convention as the other agents in this app."""
    brief = (brief or "").strip()
    if not brief:
        return []
    user_prompt = f"Brief: {brief}\n\nColumns:\n{_columns_block(df)}\n\nExtract the requirements now."
    raw = chat_json(CLIENT_BRIEF_SYSTEM_PROMPT, user_prompt)
    return [
        {**item, "type": "derived_feature", "source": "CLIENT_REQUESTED"}
        for item in _parse_requirement_items(raw, "client_requirements")
    ]


def suggest_additional_features(brief: str, client_requirements: list[dict], df: pd.DataFrame) -> list[dict]:
    """Section 3: AI-suggested extras. Fails soft (empty list) -- an
    unavailable suggestion agent shouldn't block the client's own explicit
    requirements from being created."""
    brief = (brief or "").strip()
    if not brief:
        return []
    existing = "\n".join(f"- {r['feature_name']}: {r['description']}" for r in client_requirements) or "(none)"
    user_prompt = (
        f"Brief: {brief}\n\nAlready planned features:\n{existing}\n\n"
        f"Columns:\n{_columns_block(df)}\n\nSuggest additional features now."
    )
    try:
        raw = chat_json(AI_SUGGEST_SYSTEM_PROMPT, user_prompt)
    except Exception:
        return []
    try:
        return [
            {**item, "type": "derived_feature", "source": "AI_SUGGESTED"}
            for item in _parse_requirement_items(raw, "ai_suggested")
        ]
    except (json.JSONDecodeError, AttributeError):
        return []


def infer_data_type(series: pd.Series) -> str:
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    return "categorical"


def dependency_ids(source_columns: list[str], raw_columns: set[str]) -> list[str]:
    """Section 7: a source column this feature reads that is NOT one of the
    raw data's own columns must be another feature's output -- either
    created earlier in this same batch, or already sitting in the KPI Store
    from a previous run. Recorded as the upstream feature's own kpi_store id
    so the registry entry says not just THAT it depends on something, but
    on exactly which registered feature."""
    deps: list[str] = []
    for col in source_columns:
        if col in raw_columns:
            continue
        upstream = next((e for e in kpi_store.store.all() if e.get("output_column") == col), None)
        if upstream:
            deps.append(upstream["id"])
    return deps


def spec_source_columns(spec: dict, available_columns: list[str] | None = None) -> list[str]:
    """The raw columns a spec reads from, for the KPI Store's own record
    (section 8) and for find_equivalent's column-overlap signal. Every
    template type names its columns directly in the spec; an "ai_generated"
    one only has a plain-English calculation_prompt, so this falls back to
    a best-effort scan for which of the CURRENT dataframe's column names are
    literally mentioned in it."""
    cols: list[str] = []
    for key in ("start_column", "end_column"):
        if spec.get(key):
            cols.append(spec[key])
    for key in ("numerator_columns", "denominator_columns", "source_columns"):
        if spec.get(key):
            cols.extend(spec[key])
    if not cols and spec.get("type") == "ai_generated" and available_columns:
        prompt = (spec.get("calculation_prompt") or "").lower()
        cols = [c for c in available_columns if c.lower() in prompt]
    return sorted(set(cols))


def create_or_reuse_features(
    requirements: list[dict], df: pd.DataFrame
) -> tuple[list[RequirementOutcome], list[FeatureSuggestion], pd.DataFrame]:
    """Section 2, 3, 7, 9, 11's core loop. `requirements` is explicit client
    requirements FIRST, then AI-suggested ones -- list order is also
    priority order, since kpi_store is checked (and updated) as we go, so an
    AI suggestion that duplicates an explicit requirement processed earlier
    in the SAME call reuses it rather than creating a second column.

    Returns (outcomes -- one per requirement, in input order; accepted_specs
    -- every resulting spec, reused or newly created, ready to hand to
    feature_engineering.apply_features/the existing extra_features flow;
    working -- the dataframe with every newly created column appended, for
    a caller that wants it directly)."""
    pending = list(requirements)
    outcomes: dict[str, RequirementOutcome] = {}
    specs: dict[str, FeatureSuggestion] = {}  # feature_name -> resolved spec
    working = df.copy()
    raw_columns = set(df.columns.astype(str))

    for _pass in range(MAX_PASSES):
        if not pending:
            break
        progressed = False
        still_pending: list[dict] = []
        agent_unavailable = False

        for req in pending:
            name, desc, source = req["feature_name"], req["description"], req["source"]

            if agent_unavailable:
                # The Feature Agent itself just failed (Groq unreachable/
                # rate-limited, not "this column doesn't exist yet") --
                # every remaining item this pass would hit the same wall, so
                # stop calling out rather than burning more requests on a
                # guaranteed-repeat failure.
                still_pending.append(req)
                outcomes[name] = RequirementOutcome(
                    feature_name=name, description=desc, source=source, status="failed",
                    error="Skipped -- the Feature Agent was unavailable earlier in this batch.",
                )
                continue

            existing = kpi_store.store.find_equivalent(name, desc)
            if existing:
                specs[name] = FeatureSuggestion(**existing["spec"])
                outcomes[name] = RequirementOutcome(
                    feature_name=name, description=desc, source=source, status="reused",
                    kpi_id=existing["id"], output_column=existing.get("output_column"),
                )
                progressed = True
                continue

            try:
                spec_obj = feature_request_agent.draft_feature_spec(desc, working)
            except ValueError as exc:
                # A validation failure -- e.g. "references a column not
                # present in the current data" -- is exactly the shape a
                # not-yet-created dependency takes, so it's worth a retry
                # once another requirement has added that column.
                still_pending.append(req)
                outcomes[name] = RequirementOutcome(
                    feature_name=name, description=desc, source=source, status="failed", error=str(exc),
                )
                continue
            except Exception as exc:
                # Anything else (Groq unreachable, rate-limited, ...) won't
                # resolve itself by retrying within this same call.
                agent_unavailable = True
                still_pending.append(req)
                outcomes[name] = RequirementOutcome(
                    feature_name=name, description=desc, source=source, status="failed",
                    error=f"Feature Agent unavailable: {exc}",
                )
                continue

            spec = spec_obj.model_dump(exclude_none=True)
            new_df, results, skipped = feature_engineering.apply_features(working, [spec])
            if not results:
                # Not computable YET -- likely depends on a column another
                # requirement will create later in this call. Retry next pass.
                still_pending.append(req)
                outcomes[name] = RequirementOutcome(
                    feature_name=name, description=desc, source=source, status="failed",
                    error=(skipped[0] if skipped else "Could not be computed."),
                )
                continue

            result = results[0]
            working = new_df
            source_cols = spec_source_columns(spec, list(df.columns))
            entry = kpi_store.store.upsert(
                name=name,
                description=desc,
                source=source,
                output_column=spec["output_column"],
                spec_type=spec["type"],
                formula=spec.get("formula", ""),
                python_code=spec.get("generated_code"),
                data_type=infer_data_type(working[spec["output_column"]]),
                dependencies=dependency_ids(source_cols, raw_columns),
                source_columns=source_cols,
                spec=spec,
            )
            # Read the spec back off the registry entry, not the local
            # `spec` var -- kpi_store.upsert() re-ids it to match entry["id"]
            # (the source-prefixed bucket marker), and that's what needs to
            # ride along into accepted_specs/the recomputed feature report.
            specs[name] = FeatureSuggestion(**entry["spec"])
            outcomes[name] = RequirementOutcome(
                feature_name=name, description=desc, source=source, status="created",
                kpi_id=entry["id"], output_column=result.output_column,
            )
            progressed = True

        pending = still_pending
        if not progressed or agent_unavailable:
            break

    # Anything left after the last pass genuinely couldn't be resolved --
    # the outcome recorded during its last attempt already explains why.
    for req in pending:
        name = req["feature_name"]
        if name not in outcomes:
            outcomes[name] = RequirementOutcome(
                feature_name=name, description=req["description"], source=req["source"],
                status="failed", error="Could not be computed -- a dependency may be missing.",
            )

    ordered_outcomes = [outcomes[r["feature_name"]] for r in requirements]
    accepted_specs = [specs[r["feature_name"]] for r in requirements if r["feature_name"] in specs]
    return ordered_outcomes, accepted_specs, working
