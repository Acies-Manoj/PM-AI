"""Client Brief -> Analysis Requirements -> Formula Agent -> Analysis page.
Mirrors feature_orchestrator.py's shape exactly, one layer over analysis
instead of feature engineering; it does not introduce a second execution
engine either -- every piece it touches already exists:

  1. `extract_analysis_requirements` -- Groq reads the brief and returns
     structured JSON: one entry per DISTINCT analysis/chart/breakdown the
     client explicitly asked for (as opposed to a new column/KPI -- that's
     feature_orchestrator's job -- or a generic "suggest something"
     request, which Chart Suggestion/pivot_suggester.py already covers).
  2. `resolve_analysis_requirements` -- for every requirement, hands the
     description straight to formula_agent.answer_question (the SAME
     Formula Agent behind "Request an Analysis" and a chart's own
     drill-down "Add" -- pivot template first, sandboxed pandas otherwise).
     A result whose shape (group_by + metric) already matches a pivot
     already on the session is treated as "reused" rather than added again;
     otherwise the new pivot is prefixed "client_pivot_" (this module's own
     provenance marker, parallel to kpi_store's "client_" features) and
     handed back for the caller to append to the session -- guaranteed
     already-added, not merely suggested, the same guarantee
     feature_orchestrator gives an explicit client-requested feature.

No dependency-ordering worklist is needed here (unlike feature_orchestrator):
an analysis reads columns that already exist in the dataframe by the time a
Client Brief reaches this page (any brand-new columns a brief also asked for
were created earlier, on the Features page's own Client Brief run), so a
single pass over the requirement list is enough."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pandas as pd

from app.schemas import PivotResult
from app.services import formula_agent
from app.services.groq_client import chat_json
from app.services.llm_context import columns_block as _columns_block

ANALYSIS_BRIEF_SYSTEM_PROMPT = """You read a client's plain-language brief \
for a cold-chain shipment analytics tool and extract every DISTINCT \
analysis/chart/breakdown the client is explicitly asking to SEE -- a \
question about the data as it stands (e.g. "show X by Y", "which suppliers \
have the most Z", "trend of X over time"), not a request for a new \
calculated column/KPI to be added to the data.

You'll be given the brief plus the current column names, dtypes, and a few \
sample values per column. Extract one entry per distinct analysis, phrased \
as a self-contained question the Formula Agent can answer directly (it will \
never see the original brief, only what you write here). Use a short, \
human-readable name for each (e.g. "Delay by Supplier", "Transit Duration \
Trend by Month"). If the brief doesn't actually ask to see any analysis (it \
only asks for new columns/KPIs, or nothing at all), return an empty list --\
 do not invent one.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"analysis_requirements": [
  {"analysis_name": "Short Title Case Name",
   "description": "one self-contained question restating exactly what to show"}
]}"""


@dataclass
class AnalysisRequirementOutcome:
    analysis_name: str
    description: str
    status: str  # "reused" | "created" | "failed"
    pivot_id: str | None = None
    error: str | None = None


def extract_analysis_requirements(brief: str, df: pd.DataFrame) -> list[dict]:
    """Natural-language brief -> structured JSON. Raises whatever the Groq
    client raises (missing key, network error) -- the router turns that
    into a 502, same convention as every other agent in this app."""
    brief = (brief or "").strip()
    if not brief:
        return []
    user_prompt = f"Brief: {brief}\n\nColumns:\n{_columns_block(df)}\n\nExtract the analyses now."
    raw = chat_json(ANALYSIS_BRIEF_SYSTEM_PROMPT, user_prompt)
    payload = json.loads(raw)
    items = payload.get("analysis_requirements", []) if isinstance(payload, dict) else []
    out: list[dict] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if isinstance(item, dict) and item.get("analysis_name") and item.get("description"):
            out.append({
                "analysis_name": str(item["analysis_name"]).strip(),
                "description": str(item["description"]).strip(),
            })
    return out


def _is_duplicate(candidate: PivotResult, existing_pivots: list[PivotResult]) -> bool:
    """Same group-by shape + at least one overlapping metric as an already-
    active pivot counts as "already covered" -- cheap, deterministic, no
    extra Groq call, same spirit as kpi_store.find_equivalent for features
    and routers/analysis.py's own _pivot_is_duplicate for Chart Suggestion."""
    cand_group = set(candidate.group_by)
    cand_metrics = set(candidate.metric_labels)
    return any(
        set(p.group_by) == cand_group and cand_metrics & set(p.metric_labels)
        for p in existing_pivots
    )


def resolve_analysis_requirements(
    session_id: str, requirements: list[dict], df: pd.DataFrame, existing_pivots: list[PivotResult]
) -> tuple[list[AnalysisRequirementOutcome], list[PivotResult]]:
    """Section-11-style priority: every explicit requirement is attempted,
    in order. Returns (outcomes -- one per requirement, in input order;
    new_pivots -- every newly-created pivot, "client_pivot_"-prefixed,
    ready for the caller to append to the session same as /ask's own
    answer). `existing_pivots` grows as this call creates more, so a later
    requirement in the SAME brief that duplicates an earlier one's shape is
    also caught as "reused", not just ones from before this call."""
    outcomes: list[AnalysisRequirementOutcome] = []
    new_pivots: list[PivotResult] = []
    active = list(existing_pivots)
    agent_unavailable = False

    for req in requirements:
        name, desc = req["analysis_name"], req["description"]

        if agent_unavailable:
            outcomes.append(AnalysisRequirementOutcome(
                analysis_name=name, description=desc, status="failed",
                error="Skipped -- the Formula Agent was unavailable earlier in this batch.",
            ))
            continue

        try:
            answer = formula_agent.answer_question(session_id, desc, df)
        except ValueError as exc:
            # Could be "genuinely not computable" or "Groq itself is down
            # for both the template and custom-python paths" -- either way,
            # a retry within this same call won't help (no worklist here
            # unlike feature_orchestrator: nothing about df changes between
            # requirements), so just record it and move on to the next ask.
            outcomes.append(AnalysisRequirementOutcome(analysis_name=name, description=desc, status="failed", error=str(exc)))
            continue
        except Exception as exc:
            agent_unavailable = True
            outcomes.append(AnalysisRequirementOutcome(
                analysis_name=name, description=desc, status="failed", error=f"Formula Agent unavailable: {exc}",
            ))
            continue

        if answer.pivot is None:
            # Answered, but not as a chart (a single value or a small
            # table) -- nothing to add to the pivot list, but it's not a
            # failure either.
            outcomes.append(AnalysisRequirementOutcome(analysis_name=name, description=desc, status="created", error=None))
            continue

        if _is_duplicate(answer.pivot, active):
            match = next(
                p for p in active
                if set(p.group_by) == set(answer.pivot.group_by) and set(answer.pivot.metric_labels) & set(p.metric_labels)
            )
            outcomes.append(AnalysisRequirementOutcome(analysis_name=name, description=desc, status="reused", pivot_id=match.id))
            continue

        pivot = answer.pivot.model_copy(update={"id": f"client_pivot_{uuid.uuid4().hex[:8]}"})
        new_pivots.append(pivot)
        active.append(pivot)
        outcomes.append(AnalysisRequirementOutcome(analysis_name=name, description=desc, status="created", pivot_id=pivot.id))

    return outcomes, new_pivots
