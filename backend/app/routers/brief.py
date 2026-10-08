from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.deps import User, get_user, require_owned
from app.services.common import audit_log, doc_store

router = APIRouter(prefix="/api/brief", tags=["brief"])

LANGUAGE_NAMES: dict[str, str] = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian",
    "hu": "Hungarian", "id": "Indonesian", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian", "mk": "Macedonian",
    "ml": "Malayalam", "mr": "Marathi", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "sk": "Slovak", "sl": "Slovenian", "sq": "Albanian", "sr": "Serbian",
    "sv": "Swedish", "sw": "Swahili", "ta": "Tamil", "te": "Telugu",
    "th": "Thai", "tl": "Filipino", "tr": "Turkish", "uk": "Ukrainian",
    "ur": "Urdu", "vi": "Vietnamese", "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
}


class DetectTranslateRequest(BaseModel):
    text: str
    target_language: str = "EN"


class DetectTranslateResponse(BaseModel):
    detected_language: str
    detected_language_name: str
    is_english: bool
    translated_text: str | None = None
    translation_available: bool = False
    translation_error: str | None = None


class FileMetadataIn(BaseModel):
    slot: str
    filename: str
    size: int
    mime_type: str


class SaveMetadataRequest(BaseModel):
    session_id: str | None = None
    raw_brief: str
    final_brief: str
    original_language: str | None = None
    original_language_name: str | None = None
    translated_text: str | None = None
    files: list[FileMetadataIn]
    audit_session_ids: list[str] = []


class SaveMetadataResponse(BaseModel):
    session_id: str


# Client-brief translation is disabled for now -- Planner reads final_text/
# raw_text directly (see planner.py's suggest()). Commented out rather than
# removed so it can be turned back on later without reconstructing it.
#
# def _translate_deepl(text: str, target_lang: str) -> tuple[str | None, str | None]:
#     """Returns (translated_text, error_message)."""
#     body = urllib.parse.urlencode({
#         "text": text,
#         "target_lang": target_lang,
#     }).encode()
#     headers = {
#         "Authorization": f"DeepL-Auth-Key {DEEPL_API_KEY}",
#         "Content-Type": "application/x-www-form-urlencoded",
#     }
#     req = urllib.request.Request(DEEPL_API_URL, data=body, headers=headers)
#     try:
#         with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
#             data = json.loads(resp.read().decode())
#             return data["translations"][0]["text"], None
#     except urllib.error.HTTPError as e:
#         body_bytes = e.read()
#         try:
#             detail = json.loads(body_bytes).get("message", e.reason)
#         except Exception:
#             detail = e.reason
#         return None, f"DeepL {e.code}: {detail}"
#     except Exception as e:
#         return None, str(e)
#
#
# @router.post("/detect-translate", response_model=DetectTranslateResponse)
# def detect_and_translate(req: DetectTranslateRequest):
#     if not req.text.strip():
#         raise HTTPException(status_code=400, detail="Text cannot be empty.")
#
#     try:
#         from langdetect import detect
#         lang = detect(req.text)
#     except Exception:
#         lang = "en"
#
#     lang_lower = lang.lower()
#     lang_name = LANGUAGE_NAMES.get(lang_lower, lang.upper())
#     is_english = lang_lower.startswith("en")
#
#     translated: str | None = None
#     translation_error: str | None = None
#     translation_available = bool(DEEPL_API_KEY)
#
#     if not is_english and DEEPL_API_KEY:
#         translated, translation_error = _translate_deepl(req.text, req.target_language)
#
#     return DetectTranslateResponse(
#         detected_language=lang,
#         detected_language_name=lang_name,
#         is_english=is_english,
#         translated_text=translated,
#         translation_available=translation_available,
#         translation_error=translation_error,
#     )


class FinalizeRequest(BaseModel):
    audit_session_ids: list[str]
    raw_brief: str
    final_brief: str
    original_language: str | None = None
    original_language_name: str | None = None
    translated_text: str | None = None
    files: list[FileMetadataIn]


class FinalizeResponse(BaseModel):
    session_id: str


@router.post("/finalize", response_model=FinalizeResponse)
def finalize(req: FinalizeRequest, user: User = Depends(get_user)):
    """Merge brief + all uploaded datasets into one metadata.json.

    Uses the first audit session as the canonical session: the brief is stored
    as that session's BRIEF document.
    """
    if not req.audit_session_ids:
        raise HTTPException(status_code=400, detail="At least one audit_session_id is required.")
    for sid in req.audit_session_ids:
        require_owned(sid, user)

    primary_sid = req.audit_session_ids[0]

    metadata = {
        "session_id": primary_sid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "client_brief": {
            "raw_text": req.raw_brief,
            "final_text": req.final_brief,
            "original_language": req.original_language,
            "original_language_name": req.original_language_name,
            "translated_text": req.translated_text,
        },
        "files": [f.model_dump() for f in req.files],
    }

    doc_store.put(primary_sid, "BRIEF", metadata)
    audit_log.log_event(
        primary_sid, user.id, "brief_finalize",
        {"audit_session_ids": req.audit_session_ids, "files": [f.filename for f in req.files]},
    )

    return FinalizeResponse(session_id=primary_sid)
