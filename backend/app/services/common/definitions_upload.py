"""Shared "upload a definitions JSON file" flow used by the Features and
Analysis routers' /definitions POST endpoints: read -> parse JSON ->
validate against the target store's schema -> store it. The two callers
differ only in which defs_store module they pass and what they name the
uploaded file by default.
"""
import json

from fastapi import HTTPException, UploadFile


async def upload_definitions(file: UploadFile, defs_store, default_filename: str) -> tuple[str, list[dict]]:
    """Validates and stores the uploaded file via `defs_store.validate` /
    `defs_store.store.set`. Returns (filename, validated definitions).
    Raises HTTPException(422) on anything empty, unparseable, or invalid."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        definitions = defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or default_filename
    defs_store.store.set(filename, definitions)
    return filename, definitions
