"""Dev convenience only: serves the bundled sample files under
backend/data/raw/ so the Upload page's "Add all samples" button can fetch
them as real files and feed them through the exact same onSelect/
setMatrixFiles path a manual file pick would -- no special-cased upload
logic needed anywhere downstream, and no dependence on any one developer's
own Desktop copies."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import RAW_DATA_DIR

router = APIRouter(prefix="/api/samples", tags=["samples"])

# Upload-slot id -> (filename under backend/data/raw/, content type). The
# customerKpis/analysisProfile pair is the SAME file feature_definitions_
# store.py/pivot_definitions_store.py already load as the bundled default
# when nothing is uploaded -- included anyway so "Add all samples" exercises
# the real upload path end to end, not just the parts with no default.
SAMPLE_FILES: dict[str, dict[str, str]] = {
    "sensiwatch": {
        "filename": "tabular_shipment_data_sample.xlsm",
        "content_type": "application/vnd.ms-excel.sheet.macroEnabled.12",
    },
    "temperatureMatrix": {
        "filename": "temperature_matrix_sample.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "lightMatrix": {
        "filename": "light_matrix_sample.xlsx",
        "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "customerKpis": {"filename": "customer_kpi_profile_example.json", "content_type": "application/json"},
    "analysisProfile": {"filename": "analysis_profile_example.json", "content_type": "application/json"},
}


@router.get("/manifest")
def get_manifest() -> dict[str, dict[str, str]]:
    return SAMPLE_FILES


@router.get("/{slot_id}")
def get_sample_file(slot_id: str) -> FileResponse:
    entry = SAMPLE_FILES.get(slot_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No sample file for slot '{slot_id}'.")
    path = RAW_DATA_DIR / entry["filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Sample file '{entry['filename']}' is missing on the server.")
    return FileResponse(path, media_type=entry["content_type"], filename=entry["filename"])
