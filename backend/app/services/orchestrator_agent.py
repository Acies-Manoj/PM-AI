"""Reads the client's free-text brief up front and decides which of the two
entry points it belongs to:

  "feature_request" -- the brief is asking for a new column/KPI to be added
                        to the data (e.g. "add a flag for supplier country
                        of origin") -- routes to features.py's /request.
  "analysis_question" -- the brief is asking a question about the data
                        itself (e.g. "what's the average excursion time for
                        Supplier X?") -- routes to analysis.py's /ask.

The brief is translated to English FIRST (via translation_service.py's
DeepL wrapper, auto-detecting the source language) -- that's what makes it
"orchestration-understandable": every downstream agent (Feature Agent,
Formula Agent, ...) reads and writes English, same as the rest of this app.
A brief already in English, or DeepL being unavailable, is a no-op there.
The detected language and the translated text ride along on the response
(`detected_language`/`translated_text`, both `None` when nothing was
actually translated) so the UI can show the user what their brief was
understood as, instead of silently working from a rephrasing they never see.

Past that, Groq only classifies and lightly rephrases the ask for the next
agent; it never computes anything itself. If Groq is unavailable or returns
something unusable, this fails safe to "analysis_question" (the more
general of the two) rather than blocking the caller -- a wrong guess here
just means the next agent gets a slightly less-focused prompt, not a broken
pipeline.
"""
import json

from app.schemas import OrchestratorRouteResponse
from app.services import translation_service
from app.services.groq_client import chat_json

SYSTEM_PROMPT = """You triage one-line requests for a cold-chain shipment \
analytics tool with two possible destinations:

- "feature_request": the user wants a NEW column/KPI computed and added to \
their data (e.g. "add country of origin", "flag trips where the unit was \
swapped mid-trip", "give me % of trip time in spec as a column").
- "analysis_question": the user is asking a QUESTION about the data as it \
already stands, or wants a chart/pivot/summary (e.g. "what's the average \
excursion time by supplier?", "show me July trips for Origin=Chicago", \
"why did trip 4021 get flagged?").

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"path": "feature_request" | "analysis_question",
 "cleaned_request": "the user's ask, lightly cleaned up but not reworded in meaning",
 "rationale": "one short sentence on why you picked that path"}"""


def route_brief(brief: str) -> OrchestratorRouteResponse:
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("The client brief is empty -- nothing to route.")
    original_brief = brief
    translation = translation_service.translate_to_english(brief)
    brief = translation.text
    # Only worth surfacing when something actually changed -- a brief that
    # was already English (or that DeepL couldn't reach) shouldn't show a
    # "translated" panel that's identical to what the user typed.
    was_translated = translation.detected_lang_code not in (None, "EN") and brief != original_brief

    try:
        raw = chat_json(SYSTEM_PROMPT, f"Brief: {brief}\n\nClassify it now.")
        payload = json.loads(raw)
        path = payload.get("path")
        if path not in ("feature_request", "analysis_question"):
            raise ValueError(f"unexpected path '{path}'")
        cleaned_request = str(payload.get("cleaned_request") or brief).strip()
        rationale = str(payload.get("rationale") or "").strip()
    except Exception:
        # Fail safe rather than fail closed: an unreadable/unavailable
        # classifier shouldn't block the user, it should just hand the raw
        # brief to the more general of the two paths.
        path, cleaned_request, rationale = "analysis_question", brief, (
            "Routing agent was unavailable or returned an unexpected response -- "
            "defaulted to the analysis path with the brief as given."
        )

    return OrchestratorRouteResponse(
        path=path,
        cleaned_request=cleaned_request,
        rationale=rationale,
        detected_language=translation.detected_lang_name or translation.detected_lang_code if was_translated else None,
        translated_text=brief if was_translated else None,
    )
