"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"

# Where user-created KPIs/analyses are persisted between sessions (see
# custom_library_store.py) -- the one thing in this app that survives a
# restart, since "keep it as my regular" is meaningless if it doesn't.
CUSTOM_LIBRARY_PATH = DATA_DIR / "custom_library.json"

# Log of what Step 3's AI agents have already produced per session -- AI
# summaries, chart interpretations, drill-down suggestions, ask-a-question
# results (see analysis_store.py). Same rationale as CUSTOM_LIBRARY_PATH:
# worth surviving a restart so a re-asked question doesn't always recompute.
ANALYSIS_STORE_PATH = DATA_DIR / "analysis_store.json"

# Central, durable registry of every feature created or reused via the
# Client Brief / user-request pipeline (see kpi_store.py, feature_
# orchestrator.py) -- provenance (CLIENT_REQUESTED/AI_SUGGESTED/USER_
# REQUESTED), source columns, formula, and the spec needed to recompute it.
KPI_STORE_PATH = DATA_DIR / "kpi_store.json"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Optional -- a genuinely separate account/quota from Groq (Groq's own rate
# limits are enforced per-ORGANIZATION, so a second Groq key would NOT help;
# OpenRouter is a different provider entirely). Takes priority over Groq
# when set -- see services/groq_client.py, which every agent in this app
# already goes through, so setting this one variable is enough to move all
# of them off Groq at once.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")

# Optional -- report translation only (see translation_service.py). A report
# download still succeeds without this set; it just stays in English.
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]
