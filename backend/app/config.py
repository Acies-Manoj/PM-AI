"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# One model per agent role, chosen for cost -- override any of these in .env.
# A full pipeline run (orchestrator + audit narrator + feature agent +
# insight agent + formula agent) costs well under a cent at these prices.
MODEL_ORCHESTRATOR = os.getenv("MODEL_ORCHESTRATOR", "google/gemini-3.5-flash-lite")
MODEL_AUDIT_NARRATOR = os.getenv("MODEL_AUDIT_NARRATOR", "meta-llama/llama-3.1-8b-instruct")
MODEL_FEATURE_AGENT = os.getenv("MODEL_FEATURE_AGENT", "qwen/qwen-2.5-coder-32b-instruct")
MODEL_INSIGHT_AGENT = os.getenv("MODEL_INSIGHT_AGENT", "google/gemini-3.5-flash-lite")
MODEL_FORMULA_AGENT = os.getenv("MODEL_FORMULA_AGENT", "qwen/qwen-2.5-coder-32b-instruct")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]
