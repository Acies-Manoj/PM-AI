from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.routers import analysis, audit, brief, features, report, screening

app = FastAPI(title="Cold Chain Analysis Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit.router)
app.include_router(features.router)
app.include_router(brief.router)
app.include_router(screening.router)
app.include_router(analysis.router)
app.include_router(report.router)


@app.get("/health")
def health():
    return {"status": "ok"}
