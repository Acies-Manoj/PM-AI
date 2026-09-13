"""Reads the client brief and extracts key analysis questions and a pipeline
description. The pipeline is always the full path:
audit → screening → features → analysis → report.
"""
from app.config import MODEL_ORCHESTRATOR
from app.schemas import BriefAnalysis
from app.services.openrouter_client import chat_json

_SYSTEM = """You are the orchestrator for a cold-chain data-analysis pipeline. \
The pipeline always runs in full: audit → threshold screening → \
feature engineering → AI analysis → report.

Given a client brief, extract the following and respond as a JSON object with \
EXACTLY these keys:

- "key_questions": a JSON array of 1-5 strings — specific questions the \
analysis should answer, extracted or inferred from the brief
- "pipeline_description": one paragraph describing what the pipeline will do \
for this client, based on their brief

Respond with ONLY the JSON object."""


def analyze_brief(brief_text: str) -> BriefAnalysis:
    data = chat_json(
        _SYSTEM,
        f"Client brief:\n\n{brief_text}\n\nRespond as JSON.",
        model=MODEL_ORCHESTRATOR,
        temperature=0.1,
    )
    if not data:
        data = {
            "key_questions": [],
            "pipeline_description": "Full cold-chain analysis pipeline will run on the uploaded data.",
        }
    return BriefAnalysis(**data)
