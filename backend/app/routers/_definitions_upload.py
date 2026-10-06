"""Shared body of the two "upload a JSON definitions file" routes
(features.py's /definitions and analysis.py's /definitions): read -> reject
empty -> parse JSON -> validate against the store's own schema -> save ->
build the response. Only what happens after a valid file differs (the
response shape and its field names), so that part stays a small callback
each router supplies."""
import json
from typing import Callable

from fastapi import HTTPException, UploadFile


async def upload_definitions(
    file: UploadFile,
    defs_store,
    default_filename: str,
    build_summary: Callable[[str, list[dict]], object],
):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        entries = defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or default_filename
    defs_store.store.set(filename, entries)

    return build_summary(filename, entries)
