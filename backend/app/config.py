"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
# Low-cost default: google/gemini-2.5-flash-lite (very cheap, fast).
# Override in .env with any model slug from https://openrouter.ai/models
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash-lite")

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")

# The Feature Agent (think / write code / validate) runs entirely on
# OpenRouter -- never Groq. Defaults to the same cost-effective model as the
# Planner; override independently in .env if a different model suits the
# code-generation + validation workload better.
FEATURE_AGENT_MODEL = os.getenv("FEATURE_AGENT_MODEL", OPENROUTER_MODEL)

# The Analysis Agent (think / write code / choose chart / write chart spec /
# interpret / suggest drilldowns) runs entirely on OpenRouter -- same
# convention as the Feature Agent above.
ANALYSIS_AGENT_MODEL = os.getenv("ANALYSIS_AGENT_MODEL", OPENROUTER_MODEL)

# Guided drill-down proposals (which dimension / focus / top-N to drill into
# next). A small JSON-only call, but a wrong pick sends the PM down the wrong
# chain, so it can be pointed at a stronger model than the rest of the agent.
DRILLDOWN_AGENT_MODEL = os.getenv("DRILLDOWN_AGENT_MODEL", "anthropic/claude-sonnet-4")

# The Planner turns a client brief into features and analyses. A wrong reading here
# (merged breakdowns, a dropped threshold) misleads every later step, so it can be
# pointed at a stronger model than the rest of the app.
PLANNER_AGENT_MODEL = os.getenv("PLANNER_AGENT_MODEL", "anthropic/claude-sonnet-4")

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:5175",
]


# =====================================================================================
# MODEL PER LLM CALL
#
# Every LLM call has a name (its `call_name`, also what backend/data/token_usage.jsonl
# records). MODEL_BY_CALL gives each call its own model, so the heavy-reasoning calls can
# use a stronger model than the cheap, high-volume ones.
#
# Going back:
#   * the model each call used BEFORE this table is in the comment on its line, and
#   * USE_PER_CALL_MODELS=0 (env) ignores this whole table and falls back to the older
#     per-agent settings above (LLM_MODEL, OPENROUTER_MODEL, FEATURE_AGENT_MODEL,
#     ANALYSIS_AGENT_MODEL, DRILLDOWN_AGENT_MODEL, PLANNER_AGENT_MODEL).
# Trying one call: set MODEL_<CALL NAME IN CAPITALS> in .env, e.g.
#   MODEL_ANALYSIS_AGENT_INTERPRET=anthropic/claude-sonnet-4.5
# Names below are OpenRouter slugs. (To call AWS Bedrock directly instead, the app needs a
# Bedrock client; the Bedrock model ids differ, e.g. anthropic.claude-sonnet-4-5-...)
# =====================================================================================
# Longest answer any LLM call may produce. OpenRouter RESERVES credit for the full
# max_tokens of a call, and Claude models default to a very large one (64,000), so a call
# with no limit can be refused with "402: requires more credits" even though the real
# answer is tiny. Every call sets a limit; raise this only if answers get cut off.
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "6000"))

USE_PER_CALL_MODELS = os.getenv("USE_PER_CALL_MODELS", "1") != "0"

SONNET_45 = "anthropic/claude-sonnet-4.5"
SONNET_46 = "anthropic/claude-sonnet-4.6"
HAIKU_45 = "anthropic/claude-haiku-4.5"
NOVA_PRO = "amazon/nova-pro-v1"

MODEL_BY_CALL: dict[str, str] = {
    # -- Planner and drill-down path design: reasoning that decides what gets built ----------
    "planner_agent": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): SONNET_45
    "drilldown_path": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): SONNET_45 -- was claude-sonnet-4

    # -- Feature agent: think = designs the formula, write_code = pandas, validate = checks ---
    "feature_agent_think": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): SONNET_45
    "feature_agent_write_code": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45
    "feature_agent_validate": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45
    "feature_suggester": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45

    # -- Analysis agent ----------------------------------------------------------------------
    "analysis_agent_think": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): SONNET_45
    "analysis_agent_write_code": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45
    "analysis_agent_chart_suggestion": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45
    "analysis_agent_interpret": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45

    # -- Analysis designer (custom analyses, template matching) ------------------------------
    "analysis_designer_template_match": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): SONNET_46
    "analysis_designer_chart": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45
    "analysis_suggester": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45

    # -- Drill-down suggestions --------------------------------------------------------------
    "drilldown_agent": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45
    "drilldown_agent_more": "openai/gpt-4o-mini",  # trial (Anthropic/Nova): HAIKU_45

    # -- Summaries -----------------------------------------------------------------------------
    "audit_agent": "google/gemini-2.5-flash-lite",  # trial (Anthropic/Nova): NOVA_PRO
    "overall_analysis_agent": "google/gemini-2.5-flash-lite",  # trial (Anthropic/Nova): NOVA_PRO
    "report_final_summary_agent": "google/gemini-2.5-flash-lite",  # trial (Anthropic/Nova): HAIKU_45
}


def model_for(call_name: str, legacy: str) -> str:
    """The model for one LLM call: an env override (MODEL_<CALL_NAME>) wins, then the
    table above, then `legacy` -- the older per-agent setting -- for calls not in the
    table or when USE_PER_CALL_MODELS=0 (but an env override still applies)."""
    override = os.getenv("MODEL_" + call_name.upper())
    if override:
        return override
    if USE_PER_CALL_MODELS and call_name in MODEL_BY_CALL:
        return MODEL_BY_CALL[call_name]
    return legacy
