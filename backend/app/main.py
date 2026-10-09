from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.routers import analysis, analysis_paths, audit, brief, features, planner, report
from app.routers.deps import User, get_user
from app.services.audit.audit_store import SessionConflict
from app.services.common import doc_store, token_usage

app = FastAPI(title="Cold Chain Data Audit API")

# Browsers might call this API from the origins in CORS_ORIGINS (the deployed frontend, set
# explicitly). In local development Vite's dev server auto-increments past a taken port
# (5173 -> 5174 -> ...), which drifts past any fixed list, so any localhost/127.0.0.1 port is
# also allowed while CORS_ALLOW_LOCALHOST is on (set it to 0 in production). Authentication
# is an `Authorization: Bearer` header, not cookies, so credentials are not allowed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+" if config.CORS_ALLOW_LOCALHOST else None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SessionConflict)
async def _session_conflict_handler(request: Request, exc: SessionConflict):
    return JSONResponse(
        status_code=409,
        content={"detail": "This session was changed by another request. Reload and try again."},
    )


@app.exception_handler(doc_store.VersionConflict)
async def _doc_conflict_handler(request: Request, exc: doc_store.VersionConflict):
    return JSONResponse(
        status_code=409,
        content={"detail": "This data was changed by another request. Reload and try again."},
    )


# Every /api route requires a signed-in user (a no-op while auth is disabled locally).
_auth = [Depends(get_user)]
app.include_router(brief.router, dependencies=_auth)
app.include_router(audit.router, dependencies=_auth)
app.include_router(planner.router, dependencies=_auth)
app.include_router(features.router, dependencies=_auth)
app.include_router(analysis.router, dependencies=_auth)
app.include_router(analysis_paths.router, dependencies=_auth)
app.include_router(report.router, dependencies=_auth)

# Bundled example files for the Upload page's "Add all samples" button (see
# UploadPage.tsx) -- fetched as plain static bytes and turned into File
# objects client-side, so trying the app end to end never requires hunting
# down real source files first. Not meant for anything past that: nothing
# server-side reads from this mount. Public (no auth).
app.mount("/samples", StaticFiles(directory=config.DATA_DIR / "samples"), name="samples")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/token-usage")
def token_usage_report(user: User = Depends(get_user)):
    """Per-call token usage (input/output/total) recorded by this process for
    the signed-in user, aggregated by which of the LLM calls made them."""
    return {
        "summary_by_call": token_usage.summary_by_call(user.id),
        "records": [vars(r) for r in token_usage.get_records(user.id)],
    }
