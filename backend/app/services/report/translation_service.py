"""Wraps the DeepL translation API for the small, fixed set of English
phrases the report builder itself writes onto a slide -- headings, captions,
footer legal text, and the highlight-label keywords (e.g. "Avg", "Highest").
This is NEVER handed a data value (an analysis name, interpretation
sentence, column name, or category value from the uploaded spreadsheet) --
a literal business term or proper noun isn't safe to run through a
translator, so the report builder only ever translates its own authored
words and splices data back in untouched around them (see
report_generator.py's TRANSLATABLE_PHRASES and translate_highlight_label).

Silently falls back to the original English text -- for one phrase, or for
the whole batch -- if no API key is configured, the target language isn't
one DeepL supports, or the API call itself fails (network error, rate
limit, etc). Translating the report is a nice-to-have; it should never be
the reason a report download fails.
"""
import threading

from app.config import DEEPL_API_KEY

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
        return None
    try:
        import deepl
        _client = deepl.Translator(DEEPL_API_KEY)
    except Exception:
        _client = None
    return _client


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
        for t in to_fetch:
            result[t] = t
    return result
