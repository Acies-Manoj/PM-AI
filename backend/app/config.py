"""Central config: env vars and file paths. No logic lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
# PMAI_DATA_DIR relocates local-mode storage (sessions, profiles, audit log) -- used by tests.
DATA_DIR = Path(os.environ["PMAI_DATA_DIR"]) if os.getenv("PMAI_DATA_DIR") else BACKEND_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"

# =====================================================================================
# AWS
#
# STORAGE_BACKEND is "aws" only when BOTH the docs table and the bucket are configured;
# otherwise everything falls back to local files (data/sessions/...), so `uvicorn` on a
# laptop still works with no AWS resources. In ECS, set the env vars below on the task.
# =====================================================================================
AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")
BEDROCK_REGION = os.getenv("BEDROCK_REGION", AWS_REGION)
TRANSLATE_REGION = os.getenv("TRANSLATE_REGION", AWS_REGION)

S3_BUCKET = os.getenv("S3_BUCKET", "")
DDB_SESSIONS = os.getenv("DDB_SESSIONS", "")
DDB_DOCS = os.getenv("DDB_DOCS", "")
DDB_PROFILES = os.getenv("DDB_PROFILES", "")
DDB_AUDIT = os.getenv("DDB_AUDIT", "")

USE_AWS_STORAGE = bool(S3_BUCKET and DDB_SESSIONS and DDB_DOCS)

# Sessions and their documents expire (DynamoDB TTL) this many days after last write.
SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))
AUDIT_LOG_TTL_DAYS = int(os.getenv("AUDIT_LOG_TTL_DAYS", "365"))

# Browser -> S3 direct uploads (the API Gateway body limit is 10 MB).
UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_BYTES", str(200 * 1024 * 1024)))
PRESIGN_EXPIRY_SECONDS = int(os.getenv("PRESIGN_EXPIRY_SECONDS", "900"))

# =====================================================================================
# MICROSOFT ENTRA ID
#
# Auth is enforced only when both ids are set. Unset (local dev) -> every request is the
# single user "local" and no token is needed.
# =====================================================================================
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
AUTH_ENABLED = bool(ENTRA_TENANT_ID and ENTRA_CLIENT_ID)
# Delegated scope a token must carry (the `scp` claim). Blocks app-only (client-credential)
# tokens and tokens issued for other APIs. Set to "" to skip the check.
ENTRA_REQUIRED_SCOPE = os.getenv("ENTRA_REQUIRED_SCOPE", "access_as_user")
# With AWS storage on, auth MUST be configured: otherwise every caller would be the single
# user "local" and could read everyone's sessions. Set ALLOW_ANON=1 to run open anyway
# (only sensible for a private demo).
ALLOW_ANON = os.getenv("ALLOW_ANON", "0") == "1"

# Comma-separated list of allowed browser origins, e.g. the Amplify URL.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:5175",
    ).split(",")
    if o.strip()
]
# Vite's dev server drifts to the next free port (5173 -> 5174 -> ...), so any localhost
# port is accepted too. Set CORS_ALLOW_LOCALHOST=0 in production to turn this off.
CORS_ALLOW_LOCALHOST = os.getenv("CORS_ALLOW_LOCALHOST", "1") != "0"

# =====================================================================================
# AMAZON BEDROCK
#
# BEDROCK_*_MODEL are Bedrock model ids or cross-region inference-profile ids (the "eu."
# prefix ones). The defaults below are PLACEHOLDERS for OpenAI's open-weight gpt-oss-20b, the
# lightest and cheapest model in the Stockholm catalog: copy the exact "Model ID" from the
# model's card in the Bedrock console (Model catalog) and set the env vars -- no code change.
# Other options: openai.gpt-oss-120b-1:0 (stronger), eu.amazon.nova-micro/lite/pro-v1:0.
# (Google Gemini and OpenAI's hosted GPT-4o-mini are NOT available on Bedrock.)
# =====================================================================================
# Three tiers; the cheapest setup uses the same small model for all of them. Point
# BEDROCK_STRONG_MODEL at a bigger model only if the planner / "think" / code-writing calls
# turn out unreliable.
BEDROCK_CHEAP_MODEL = os.getenv("BEDROCK_CHEAP_MODEL", "openai.gpt-oss-20b-1:0")
BEDROCK_DEFAULT_MODEL = os.getenv("BEDROCK_DEFAULT_MODEL", "openai.gpt-oss-20b-1:0")
BEDROCK_STRONG_MODEL = os.getenv("BEDROCK_STRONG_MODEL", "openai.gpt-oss-20b-1:0")

# Amazon Nova models cap the answer length per call (about 5K tokens). A request above the cap
# is rejected, so llm.py lowers max_tokens to this for any "amazon.nova" model id.
NOVA_MAX_OUTPUT_TOKENS = int(os.getenv("NOVA_MAX_OUTPUT_TOKENS", "5000"))

# The older per-agent settings are kept as the `legacy` fallback that `model_for()` takes.
LLM_MODEL = os.getenv("LLM_MODEL", BEDROCK_DEFAULT_MODEL)
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", BEDROCK_DEFAULT_MODEL)  # name kept for importers
FEATURE_AGENT_MODEL = os.getenv("FEATURE_AGENT_MODEL", BEDROCK_DEFAULT_MODEL)
ANALYSIS_AGENT_MODEL = os.getenv("ANALYSIS_AGENT_MODEL", BEDROCK_DEFAULT_MODEL)
DRILLDOWN_AGENT_MODEL = os.getenv("DRILLDOWN_AGENT_MODEL", BEDROCK_STRONG_MODEL)
PLANNER_AGENT_MODEL = os.getenv("PLANNER_AGENT_MODEL", BEDROCK_STRONG_MODEL)

# Bedrock Prompt Management: JSON object mapping a prompt name (the call_name, e.g.
# "planner_agent") to "<PROMPT_ID>" or "<PROMPT_ID>:<VERSION>". The system prompts no longer
# live in the Python code. Each call gets its prompt from Bedrock when its name is listed here;
# otherwise from backend/prompts/<name>.txt (shipped only in a dev checkout -- the Docker image
# does NOT contain them, so a deployed backend needs every prompt listed here).
BEDROCK_PROMPT_IDS = os.getenv("BEDROCK_PROMPT_IDS", "")
# Where the default prompt files are. PROMPTS_BEDROCK_ONLY=1 ignores them entirely, so a
# prompt missing from Bedrock fails loudly instead of silently using a local copy.
PROMPTS_DIR = Path(os.environ["PROMPTS_DIR"]) if os.getenv("PROMPTS_DIR") else BACKEND_DIR / "prompts"
PROMPTS_BEDROCK_ONLY = os.getenv("PROMPTS_BEDROCK_ONLY", "0") == "1"
PROMPT_CACHE_SECONDS = int(os.getenv("PROMPT_CACHE_SECONDS", "300"))


# =====================================================================================
# MODEL PER LLM CALL
#
# Every LLM call has a name (its `call_name`, also what the audit log records).
# MODEL_BY_CALL gives each call its own model, so the heavy-reasoning calls can use a
# stronger model than the cheap, high-volume ones.
#
# Trying one call: set MODEL_<CALL NAME IN CAPITALS> in the environment, e.g.
#   MODEL_ANALYSIS_AGENT_INTERPRET=eu.anthropic.claude-sonnet-4-5-20250929-v1:0
# USE_PER_CALL_MODELS=0 ignores this whole table and uses the per-agent settings above.
# =====================================================================================
# Longest answer any LLM call may produce. Every call sets a limit; raise this only if
# answers get cut off.
DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "6000"))

USE_PER_CALL_MODELS = os.getenv("USE_PER_CALL_MODELS", "1") != "0"

_C = BEDROCK_CHEAP_MODEL
_D = BEDROCK_DEFAULT_MODEL
_S = BEDROCK_STRONG_MODEL

MODEL_BY_CALL: dict[str, str] = {
    # -- Planner and drill-down path design: reasoning that decides what gets built ----------
    "planner_agent": _S,
    "drilldown_path": _S,

    # -- Feature agent: think = designs the formula, write_code = pandas, validate = checks ---
    "feature_agent_think": _S,
    "feature_agent_write_code": _D,
    "feature_agent_validate": _D,
    "feature_suggester": _D,

    # -- Analysis agent ----------------------------------------------------------------------
    "analysis_agent_think": _S,
    "analysis_agent_write_code": _D,
    "analysis_agent_chart_suggestion": _D,
    "analysis_agent_interpret": _C,
    "analysis_agent_drilldown": _D,

    # -- Analysis designer (custom analyses, template matching) ------------------------------
    "analysis_designer_template_match": _S,
    "analysis_designer_chart": _D,
    "analysis_suggester": _D,

    # -- Drill-down suggestions --------------------------------------------------------------
    "drilldown_agent": _D,
    "drilldown_agent_more": _D,

    # -- Summaries -----------------------------------------------------------------------------
    "audit_agent": _C,
    "overall_analysis_agent": _C,
    "report_final_summary_agent": _C,
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
