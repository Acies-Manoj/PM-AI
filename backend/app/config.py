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

# Default model
# Override in .env with any model slug from https://openrouter.ai/models
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4.5")

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "anthropic/claude-sonnet-4.5",
)

# The Feature Agent (think / write code / validate) runs entirely on
# OpenRouter -- never Groq.
FEATURE_AGENT_MODEL = os.getenv(
    "FEATURE_AGENT_MODEL",
    "anthropic/claude-sonnet-4.5",
)

# The Analysis Agent runs entirely on OpenRouter.
ANALYSIS_AGENT_MODEL = os.getenv(
    "ANALYSIS_AGENT_MODEL",
    "anthropic/claude-sonnet-4.5",
)

# Guided drill-down proposals.
DRILLDOWN_AGENT_MODEL = os.getenv(
    "DRILLDOWN_AGENT_MODEL",
    "anthropic/claude-sonnet-4.5",
)

# The Planner turns a client brief into features and analyses.
PLANNER_AGENT_MODEL = os.getenv(
    "PLANNER_AGENT_MODEL",
    "anthropic/claude-sonnet-4.5",
)

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")

# Free tier uses api-free.deepl.com; Pro uses api.deepl.com
DEEPL_API_URL = os.getenv(
    "DEEPL_API_URL",
    "https://api-free.deepl.com/v2/translate",
)

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]


# =====================================================================================
# MODEL PER LLM CALL
#
# Every LLM call has a name (its call_name, also what backend/data/token_usage.jsonl
# records). MODEL_BY_CALL gives each call its own model, so the heavy-reasoning calls can
# use a stronger model than the lighter execution calls.
#
# Going back:
#   * USE_PER_CALL_MODELS=0 (env) ignores this whole table and falls back to the older
#     per-agent settings above.
#
# Trying one call:
#   MODEL_<CALL NAME IN CAPITALS>=anthropic/claude-sonnet-4.5
#
# Names below are OpenRouter slugs.
# =====================================================================================

# Longest answer any LLM call may produce.
# OpenRouter reserves credit for the full max_tokens of a call.
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "6000"))

USE_PER_CALL_MODELS = os.getenv("USE_PER_CALL_MODELS", "1") != "0"


# =====================================================================================
# ANTHROPIC TRIAL MODELS
# =====================================================================================

SONNET_45 = "anthropic/claude-sonnet-4.5"
SONNET_46 = "anthropic/claude-sonnet-4.6"
HAIKU_45 = "anthropic/claude-haiku-4.5"


# =====================================================================================
# MODEL BY LLM CALL
#
# Sonnet:
#   Used for reasoning-heavy calls where incorrect interpretation can affect
#   downstream features, analyses, or drill-down paths.
#
# Haiku:
#   Used for lighter execution-oriented calls such as code generation,
#   validation, chart selection, interpretation, suggestions, and summaries.
#
# Sonnet 4.6:
#   Used for analysis template matching where stronger reasoning is useful.
# =====================================================================================

MODEL_BY_CALL: dict[str, str] = {

    # -------------------------------------------------------------------------
    # Planner and drill-down path design
    # -------------------------------------------------------------------------
    "planner_agent": SONNET_45,
    "drilldown_path": SONNET_45,

    # -------------------------------------------------------------------------
    # Feature agent
    # Think = designs the formula / approach
    # Write code = generates pandas code
    # Validate = checks the generated feature
    # -------------------------------------------------------------------------
    "feature_agent_think": SONNET_45,
    "feature_agent_write_code": HAIKU_45,
    "feature_agent_validate": HAIKU_45,
    "feature_suggester": HAIKU_45,

    # -------------------------------------------------------------------------
    # Analysis agent
    # -------------------------------------------------------------------------
    "analysis_agent_think": SONNET_45,
    "analysis_agent_write_code": HAIKU_45,
    "analysis_agent_chart_suggestion": HAIKU_45,
    "analysis_agent_interpret": HAIKU_45,
    "analysis_agent_drilldown": HAIKU_45,

    # -------------------------------------------------------------------------
    # Analysis designer
    # Custom analyses and template matching
    # -------------------------------------------------------------------------
    "analysis_designer_template_match": SONNET_46,
    "analysis_designer_chart": HAIKU_45,
    "analysis_suggester": HAIKU_45,

    # -------------------------------------------------------------------------
    # Drill-down suggestions
    # -------------------------------------------------------------------------
    "drilldown_agent": HAIKU_45,
    "drilldown_agent_more": HAIKU_45,

    # -------------------------------------------------------------------------
    # Summaries
    # -------------------------------------------------------------------------
    "audit_agent": HAIKU_45,
    "overall_analysis_agent": HAIKU_45,
    "report_final_summary_agent": HAIKU_45,
}


def model_for(call_name: str, legacy: str) -> str:
    """Return the model configured for a specific LLM call.

    Priority:
        1. MODEL_<CALL_NAME> environment variable
        2. MODEL_BY_CALL mapping when per-call models are enabled
        3. Legacy per-agent model setting

    Example:
        MODEL_ANALYSIS_AGENT_INTERPRET=anthropic/claude-sonnet-4.5
    """

    override = os.getenv("MODEL_" + call_name.upper())

    if override:
        return override

    if USE_PER_CALL_MODELS and call_name in MODEL_BY_CALL:
        return MODEL_BY_CALL[call_name]

    return legacy
