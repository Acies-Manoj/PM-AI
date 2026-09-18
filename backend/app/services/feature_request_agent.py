"""AI agent behind the "User Requests a Feature" entry point: unlike
feature_suggester.py (which proposes ideas the user didn't ask for), this
takes ONE specific plain-language ask -- e.g. "add country of origin from
the Origin field" or "flag trips where the sensor unit changed mid-trip" --
and drafts exactly one feature spec for it.

Same guardrail as feature_suggester.py: Groq only decides HOW to express the
request, never computes a value itself, and the same three deterministic
templates (duration_hours, ratio, extract_month) are tried first. Only when
none of those fit does this fall back to `type: "ai_generated"` --
feature_engineering.py's existing ai_generated path (backed by
ai_feature_generator.py + the sandboxed ai_code_executor.py) then writes and
runs the actual pandas snippet. That reuse is deliberate: this module's only
new job is turning a free-text ask into a spec feature_engineering.py
already knows how to run -- not a second execution engine.
"""
import json
import uuid

import pandas as pd

from app.schemas import FeatureSuggestion
from app.services.feature_suggester import VALID_TYPES, _formula_text, _referenced_columns
from app.services.groq_client import chat_json
from app.services.llm_context import columns_block as _columns_block

SYSTEM_PROMPT = """You are a data engineer turning ONE specific request into \
a new engineered column for an operational cold-chain shipment dataset. \
You'll be given the request in the user's own words, plus the current \
column names, dtypes, and a few sample values per column.

Prefer expressing the request as exactly one of these three computable \
types when it genuinely fits -- never force a fit that distorts the \
request:

1. "duration_hours" -- the difference between two datetime-like columns.
   Required fields: start_column, end_column, unit ("hours" or "days").
2. "ratio" -- percentage of a sum of numerator column(s) over a sum of \
denominator column(s). Both must be numeric columns.
   Required fields: numerator_columns (list), denominator_columns (list).
3. "extract_month" -- calendar month extracted from one or more datetime \
columns (first non-null one wins).
   Required fields: source_columns (list).

If (and only if) the request genuinely needs custom logic none of those \
three can express (e.g. a lookup table, a flag with multiple conditions, a \
text transformation), respond with type "ai_generated" instead and a \
"calculation_prompt" field: a clear, self-contained instruction another \
engineer could implement in pandas, describing the calculation in plain \
English (you are NOT writing the code yourself here).

Every suggestion MUST reference only columns that appear in the given \
column list -- never invent a column name.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"name": "short title", "description": "one plain-English sentence on what this computes",
 "output_column": "short column name for the new field",
 "type": "duration_hours | ratio | extract_month | ai_generated",
 ... the required fields for that type (calculation_prompt for ai_generated) ...}"""


def draft_feature_spec(request_text: str, df: pd.DataFrame) -> FeatureSuggestion:
    """Raises ValueError if the request can't be turned into a usable spec
    (e.g. it references a column that doesn't exist) -- the router turns
    that into a 422 rather than a 500, same convention as
    feature_definitions_store.validate."""
    request_text = (request_text or "").strip()
    if not request_text:
        raise ValueError("The feature request is empty.")

    user_prompt = f"Request: {request_text}\n\nColumns:\n{_columns_block(df)}\n\nDraft the spec now."
    raw = chat_json(SYSTEM_PROMPT, user_prompt)
    spec = json.loads(raw)
    if not isinstance(spec, dict):
        raise ValueError("The feature agent returned something other than a single spec object.")

    if not spec.get("name") or not spec.get("output_column"):
        raise ValueError("The feature agent's draft is missing a name or output column.")

    spec_type = spec.get("type")
    available_columns = set(df.columns.astype(str))

    if spec_type == "ai_generated":
        calculation_prompt = (spec.get("calculation_prompt") or "").strip()
        if not calculation_prompt:
            raise ValueError("The feature agent's ai_generated draft is missing a calculation_prompt.")
        return FeatureSuggestion(
            id=f"custom_{uuid.uuid4().hex[:8]}",
            name=spec["name"],
            description=spec.get("description", request_text),
            output_column=spec["output_column"],
            type="ai_generated",
            formula=calculation_prompt,
            summary="stats",
            calculation_prompt=calculation_prompt,
        )

    if spec_type not in VALID_TYPES:
        raise ValueError(
            f"The feature agent returned an unsupported type '{spec_type}' -- expected one of "
            f"{sorted(VALID_TYPES)} or 'ai_generated'."
        )

    referenced = _referenced_columns(spec)
    if not referenced or not referenced.issubset(available_columns):
        missing = sorted((referenced or set()) - available_columns)
        raise ValueError(
            f"The feature agent's draft references column(s) not present in the current data: {', '.join(missing)}."
        )

    return FeatureSuggestion(
        id=f"custom_{uuid.uuid4().hex[:8]}",
        name=spec["name"],
        description=spec.get("description", request_text),
        output_column=spec["output_column"],
        type=spec_type,
        formula=_formula_text(spec),
        summary="distribution" if spec_type == "extract_month" else "stats",
        start_column=spec.get("start_column"),
        end_column=spec.get("end_column"),
        unit=spec.get("unit"),
        numerator_columns=spec.get("numerator_columns"),
        denominator_columns=spec.get("denominator_columns"),
        source_columns=spec.get("source_columns"),
    )
