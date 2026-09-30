from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS, DATA_DIR
from app.routers import analysis, audit, brief, features, planner, report
from app.services.common import token_usage

app = FastAPI(title="Cold Chain Data Audit API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # Vite's dev server auto-increments past a taken port (5173 -> 5174 ->
    # ...) every time an old instance is still holding one, which drifts
    # past CORS_ORIGINS' fixed list after a few restarts. Matching any
    # localhost/127.0.0.1 port covers that without having to keep guessing
    # -- this app has no cookie-based auth for the regex's broader match to
    # put at risk, and it's dev-only in intent (the deployed frontend origin
    # should still be added to CORS_ORIGINS explicitly for production).
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(brief.router)
app.include_router(audit.router)
app.include_router(planner.router)
app.include_router(features.router)
app.include_router(analysis.router)
app.include_router(report.router)

# Bundled example files for the Upload page's "Add all samples" button (see
# UploadPage.tsx) -- fetched as plain static bytes and turned into File
# objects client-side, so trying the app end to end never requires hunting
# down real source files first. Not meant for anything past that: nothing
# server-side reads from this mount.
app.mount("/samples", StaticFiles(directory=DATA_DIR / "samples"), name="samples")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/token-usage")
def token_usage_report():
    """Per-call token usage (input/output/total) recorded since this
    process started, aggregated by which of the 8 LLM calls made them."""
    return {
        "summary_by_call": token_usage.summary_by_call(),
        "records": [vars(r) for r in token_usage.get_records()],
    }
