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
# Low-cost default: google/gemini-2.5-flash-lite (very cheap, fast).
# Override in .env with any model slug from https://openrouter.ai/models
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash-lite")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
# Free tier uses api-free.deepl.com; Pro uses api.deepl.com
DEEPL_API_URL = os.getenv("DEEPL_API_URL", "https://api-free.deepl.com/v2/translate")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]
