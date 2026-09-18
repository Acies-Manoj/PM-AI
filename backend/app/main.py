from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.routers import analysis, audit, features, orchestrator, raw_data, samples

app = FastAPI(title="Cold Chain Data Audit API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audit.router)
app.include_router(features.router)
app.include_router(analysis.router)
app.include_router(raw_data.router)
app.include_router(orchestrator.router)
app.include_router(samples.router)


@app.get("/health")
def health():
    return {"status": "ok"}
