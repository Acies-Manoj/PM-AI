"""Language detection (langdetect) + translation (DeepL API).

Requires DEEPL_API_KEY in the environment. Free-tier keys end with ':fx'.
If the brief is already English the translation step is skipped entirely.
"""
import os
from dataclasses import dataclass

import deepl
from langdetect import detect, LangDetectException

# Human-readable names for ISO 639-1 codes langdetect may return.
_LANGUAGE_NAMES: dict[str, str] = {
    "af": "Afrikaans", "ar": "Arabic", "bg": "Bulgarian", "bn": "Bengali",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "fa": "Persian", "fi": "Finnish", "fr": "French",
    "gu": "Gujarati", "he": "Hebrew", "hi": "Hindi", "hr": "Croatian",
    "hu": "Hungarian", "id": "Indonesian", "it": "Italian", "ja": "Japanese",
    "kn": "Kannada", "ko": "Korean", "lt": "Lithuanian", "lv": "Latvian",
    "mk": "Macedonian", "ml": "Malayalam", "mr": "Marathi", "ms": "Malay",
    "mt": "Maltese", "nl": "Dutch", "no": "Norwegian", "pl": "Polish",
    "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sl": "Slovenian", "sq": "Albanian", "sr": "Serbian", "sv": "Swedish",
    "sw": "Swahili", "ta": "Tamil", "te": "Telugu", "th": "Thai",
    "tl": "Filipino", "tr": "Turkish", "uk": "Ukrainian", "ur": "Urdu",
    "vi": "Vietnamese", "zh-cn": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)",
}


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    detected_language: str   # ISO code, e.g. "de"
    language_name: str       # e.g. "German"
    was_translated: bool


def detect_and_translate(text: str) -> TranslationResult:
    """Detect the language of *text* and translate to English if needed.

    Raises:
        ValueError: text is empty.
        RuntimeError: DEEPL_API_KEY not set or DeepL call failed.
    """
    text = text.strip()
    if not text:
        raise ValueError("Brief text is empty.")

    # ── 1. Detect language ───────────────────────────────────────────────────
    try:
        lang_code = detect(text)
    except LangDetectException:
        lang_code = "en"  # fall back to English on detection failure

    lang_name = _LANGUAGE_NAMES.get(lang_code, lang_code.upper())

    # ── 2. If already English, return immediately ────────────────────────────
    if lang_code.startswith("en"):
        return TranslationResult(
            original_text=text,
            translated_text=text,
            detected_language=lang_code,
            language_name=lang_name,
            was_translated=False,
        )

    # ── 3. Translate via DeepL ───────────────────────────────────────────────
    api_key = os.getenv("DEEPL_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "DEEPL_API_KEY is not set. Add it to your .env file to enable translation."
        )

    try:
        translator = deepl.Translator(api_key)
        result = translator.translate_text(text, target_lang="EN-US")
    except Exception as exc:
        raise RuntimeError(f"DeepL translation failed: {exc}") from exc

    return TranslationResult(
        original_text=text,
        translated_text=result.text,
        detected_language=lang_code,
        language_name=lang_name,
        was_translated=True,
    )
