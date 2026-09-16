"""Wraps the DeepL translation API for the English PROSE that goes onto a
report slide: the builder's own fixed phrases (footer legal text, the
"Summary" heading, the highlight-label keywords like "Avg" and "Highest"),
each slide's heading and caption, and the overall-analysis narrative.

What this is never handed is a value that has to keep matching the data --
a category value read out of the uploaded spreadsheet (Italy, a carrier
name), a column name used as an axis title, or a metric label from the
Analysis Profile. Those are spliced back in untouched around the translated
prose, so a translated deck still describes the same numbers by the same
names (see report_generator.py's plan_report and translate_highlight_label).

Silently falls back to the original English text -- for one phrase, or for
the whole batch -- if no API key is configured, the target language isn't
one DeepL supports, or the API call itself fails (network error, rate
limit, etc). Translating the report is a nice-to-have; it should never be
the reason a report download fails.
"""
import logging
import threading
from dataclasses import dataclass

from app.config import DEEPL_API_KEY

logger = logging.getLogger(__name__)

# DeepL's `detected_source_lang` is a bare ISO code (e.g. "DE", "ZH") --
# this is display names for the ones it commonly detects, for
# translate_to_english's caller to show the user (e.g. the Orchestrator
# Agent's "detected language" chip). Best-effort only: an undetected/unlisted
# code just falls back to showing the raw code, never a hard failure.
_SOURCE_LANGUAGE_NAMES: dict[str, str] = {
    "AR": "Arabic", "BG": "Bulgarian", "CS": "Czech", "DA": "Danish", "DE": "German",
    "EL": "Greek", "EN": "English", "ES": "Spanish", "ET": "Estonian", "FI": "Finnish",
    "FR": "French", "HE": "Hebrew", "HI": "Hindi", "HU": "Hungarian", "ID": "Indonesian",
    "IT": "Italian", "JA": "Japanese", "KO": "Korean", "LT": "Lithuanian", "LV": "Latvian",
    "NB": "Norwegian", "NL": "Dutch", "PL": "Polish", "PT": "Portuguese", "RO": "Romanian",
    "RU": "Russian", "SK": "Slovak", "SL": "Slovenian", "SV": "Swedish", "TH": "Thai",
    "TR": "Turkish", "UK": "Ukrainian", "VI": "Vietnamese", "ZH": "Chinese",
}


@dataclass
class EnglishTranslation:
    """Result of translate_to_english: the text to actually use downstream,
    plus what DeepL detected the source language to be -- `None` for either
    language field means "couldn't detect" (no key configured, API call
    failed, ...), not "was English"; check `text == ` the original to tell
    a genuine no-op apart from an unavailable detector."""
    text: str
    detected_lang_code: str | None = None
    detected_lang_name: str | None = None

# code -> (display name, DeepL target-language code). Restricted to
# languages DeepL actually accepts as a translation TARGET -- offering one
# it doesn't support would silently fall back to English below, which would
# just be a confusing, broken-looking dropdown entry.
SUPPORTED_LANGUAGES: dict[str, tuple[str, str]] = {
    "bg": ("Bulgarian", "BG"),
    "cs": ("Czech", "CS"),
    "da": ("Danish", "DA"),
    "de": ("German", "DE"),
    "el": ("Greek", "EL"),
    "es": ("Spanish", "ES"),
    "fi": ("Finnish", "FI"),
    "fr": ("French", "FR"),
    "hu": ("Hungarian", "HU"),
    "id": ("Indonesian", "ID"),
    "it": ("Italian", "IT"),
    "ja": ("Japanese", "JA"),
    "ko": ("Korean", "KO"),
    "nl": ("Dutch", "NL"),
    "pl": ("Polish", "PL"),
    "pt": ("Portuguese", "PT-PT"),
    "ro": ("Romanian", "RO"),
    "ru": ("Russian", "RU"),
    "sk": ("Slovak", "SK"),
    "sv": ("Swedish", "SV"),
    "tr": ("Turkish", "TR"),
    "uk": ("Ukrainian", "UK"),
    "zh": ("Chinese", "ZH"),
}

_lock = threading.Lock()
_cache: dict[tuple[str, str], str] = {}
_client = None
_client_init_attempted = False


def _get_client():
    """Lazy, once-per-process DeepL client -- import + construction only
    happens the first time a real translation is actually needed, so a
    session with no configured key (or that only ever downloads in English)
    never pays for it."""
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True
    if not DEEPL_API_KEY:
        logger.warning("DEEPL_API_KEY is not set -- reports will stay in English.")
        return None
    try:
        import deepl
        _client = deepl.Translator(DEEPL_API_KEY)
    except Exception:
        # Logged, not raised: a report still downloads without translation.
        # Silently swallowing this is what makes "the language picker does
        # nothing" impossible to diagnose, so it always leaves a trace.
        logger.exception("Could not create the DeepL client -- reports will stay in English.")
        _client = None
    return _client


def is_available() -> bool:
    """Whether a translation would actually do anything -- i.e. a key is
    configured AND the deepl package imports AND the client constructs.
    Surfaced through /api/analysis/languages so the Report page can say
    "translation is off" outright, instead of offering a picker that
    silently returns English (which is exactly what a missing `deepl`
    install, or an unset key, looks like from the outside)."""
    return _get_client() is not None


def translate_many(texts: list[str], target_lang: str) -> dict[str, str]:
    """Returns {original_text: translated_text} for every text in `texts`.
    `target_lang` is one of this module's own SUPPORTED_LANGUAGES keys (or
    "en", a no-op). Anything that can't be translated -- "en", an
    unrecognized code, no API key configured, or the API call itself
    failing -- maps every text to itself rather than raising."""
    unique_texts = list(dict.fromkeys(texts))  # de-dup, preserve order
    if target_lang == "en" or target_lang not in SUPPORTED_LANGUAGES:
        return {t: t for t in unique_texts}

    result: dict[str, str] = {}
    to_fetch: list[str] = []
    with _lock:
        for t in unique_texts:
            cached = _cache.get((t, target_lang))
            if cached is not None:
                result[t] = cached
            else:
                to_fetch.append(t)

    if not to_fetch:
        return result

    client = _get_client()
    if client is None:
        for t in to_fetch:
            result[t] = t
        return result

    deepl_target = SUPPORTED_LANGUAGES[target_lang][1]
    try:
        translations = client.translate_text(to_fetch, target_lang=deepl_target)
        with _lock:
            for original, translation in zip(to_fetch, translations):
                translated_text = translation.text
                _cache[(original, target_lang)] = translated_text
                result[original] = translated_text
    except Exception:
        logger.exception("DeepL translation to %r failed -- falling back to English.", target_lang)
        for t in to_fetch:
            result[t] = t
    return result


def translate_to_english(text: str) -> EnglishTranslation:
    """The reverse direction of translate_many: a short user-typed phrase --
    the client brief the Orchestrator Agent reads (see orchestrator_agent.py)
    -- translated INTO English, auto-detecting the source language rather
    than assuming one (DeepL does this when `source_lang` is omitted, and
    reports what it detected back on the result object). Same fallback
    philosophy as the rest of this module: no configured key, an
    already-English phrase, or a failed API call all just return the
    original text unchanged (with no detected language) rather than raising
    -- a missed translation should degrade to "assume it was already
    English", never block the request that's waiting on it."""
    text = (text or "").strip()
    if not text:
        return EnglishTranslation(text=text)
    client = _get_client()
    if client is None:
        return EnglishTranslation(text=text)
    try:
        result = client.translate_text(text, target_lang="EN-US")
        code = getattr(result, "detected_source_lang", None)
        code = code.upper() if code else None
        return EnglishTranslation(
            text=result.text, detected_lang_code=code, detected_lang_name=_SOURCE_LANGUAGE_NAMES.get(code) if code else None
        )
    except Exception:
        logger.exception("DeepL translation to English failed -- using the original text.")
        return EnglishTranslation(text=text)
