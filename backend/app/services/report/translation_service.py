"""Wraps the Amazon Translate API for the report builder's own text: its
fixed English phrases -- headings, captions, footer legal text -- plus each
analysis entry's name and interpretation (natural-language sentences the
Analysis Agent or the PM wrote, translatable like any other prose). This is
NEVER handed a raw data value (a number, column name, or category value
pulled straight from the uploaded spreadsheet) -- those aren't safe to run
through a translator, so the report builder always splices them back in
untouched around whatever text it does translate (see report_generator.py's
TRANSLATABLE_PHRASES and translate_entry_texts). The closing summary's own
bullet points (final_summary_agent.py) are never translated either -- same
rule as an entry's interpretation would suggest translating them, but
they're synthesized fresh per download in English and not worth a second
translation pass on top of the per-entry one.

Silently falls back to the original English text -- for one phrase -- if
Amazon Translate is unreachable / not permitted, the target language isn't
one it supports, the text is too long for one request, or the API call itself
fails (throttling, etc). Translating the report is a nice-to-have; it should never be
the reason a report download fails.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app.services.common import aws_clients, request_context

# Amazon Translate rejects a request over 10,000 bytes; leave a margin and
# leave anything longer untranslated.
MAX_TEXT_BYTES = 9000
MAX_WORKERS = 4

log = logging.getLogger(__name__)

# code -> (display name, Amazon Translate language code). Restricted to
# languages Amazon Translate accepts as a translation TARGET (from English) -- offering one
# it doesn't support would silently fall back to English below, which would
# just be a confusing, broken-looking dropdown entry.
SUPPORTED_LANGUAGES: dict[str, tuple[str, str]] = {
    "bg": ("Bulgarian", "bg"),
    "cs": ("Czech", "cs"),
    "da": ("Danish", "da"),
    "de": ("German", "de"),
    "el": ("Greek", "el"),
    "es": ("Spanish", "es"),
    "fi": ("Finnish", "fi"),
    "fr": ("French", "fr"),
    "hu": ("Hungarian", "hu"),
    "id": ("Indonesian", "id"),
    "it": ("Italian", "it"),
    "ja": ("Japanese", "ja"),
    "ko": ("Korean", "ko"),
    "nl": ("Dutch", "nl"),
    "pl": ("Polish", "pl"),
    "pt": ("Portuguese", "pt-PT"),
    "ro": ("Romanian", "ro"),
    "ru": ("Russian", "ru"),
    "sk": ("Slovak", "sk"),
    "sv": ("Swedish", "sv"),
    "tr": ("Turkish", "tr"),
    "uk": ("Ukrainian", "uk"),
    "zh": ("Chinese", "zh"),
}

_lock = threading.Lock()
_cache: dict[tuple[str, str], str] = {}


def _translate_one(text: str, target_code: str) -> str:
    """One Amazon Translate call; returns `text` unchanged on any failure."""
    if not text.strip() or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        return text
    try:
        resp = aws_clients.translate().translate_text(
            Text=text, SourceLanguageCode="en", TargetLanguageCode=target_code
        )
        return resp["TranslatedText"] or text
    except Exception as exc:  # noqa: BLE001 - a failed translation must not fail the report
        # Say why (typically AccessDenied on translate:TranslateText, or an unsupported
        # language pair) instead of silently producing an English report.
        log.warning("Amazon Translate failed for target %s: %s", target_code, exc)
        return text


def translate_many(texts: list[str], target_lang: str) -> dict[str, str]:
    """Returns {original_text: translated_text} for every text in `texts`.
    `target_lang` is one of this module's own SUPPORTED_LANGUAGES keys (or
    "en", a no-op). Anything that can't be translated -- "en", an
    unrecognized code, an oversized string, or the API call itself
    failing -- maps that text to itself rather than raising."""
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

    target_code = SUPPORTED_LANGUAGES[target_lang][1]
    # Amazon Translate has no batch call: one request per string, a few at a time.
    # (one wrapped callable per task -- a copied Context can only be entered by one thread at once)
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(to_fetch))) as pool:
        futures = [(t, pool.submit(request_context.wrap(_translate_one), t, target_code)) for t in to_fetch]
        for original, fut in futures:
            try:
                translated = fut.result()
            except Exception:
                translated = original
            result[original] = translated
            # Only cache real translations, so a transient failure is retried next time.
            if translated != original:
                with _lock:
                    _cache[(original, target_lang)] = translated
    return result
