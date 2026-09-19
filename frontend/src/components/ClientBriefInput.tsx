import { useCallback, useRef, useState } from "react";
import "./ClientBriefInput.css";

export interface BriefState {
  rawText: string;
  detectedLanguage: string | null;
  detectedLanguageName: string | null;
  isEnglish: boolean;
  translatedText: string | null;
  translationAvailable: boolean;
  translationError: string | null;
  finalText: string;
}

export const EMPTY_BRIEF: BriefState = {
  rawText: "",
  detectedLanguage: null,
  detectedLanguageName: null,
  isEnglish: true,
  translatedText: null,
  translationAvailable: false,
  translationError: null,
  finalText: "",
};

interface Props {
  value: BriefState;
  onChange: (state: BriefState) => void;
}

export default function ClientBriefInput({ value, onChange }: Props) {
  const [isDetecting, setIsDetecting] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const detectAndTranslate = useCallback(
    async (text: string) => {
      if (!text.trim() || text.trim().length < 15) return;
      setIsDetecting(true);
      try {
        const res = await fetch("/api/brief/detect-translate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (!res.ok) return;
        const data = await res.json();
        onChange({
          rawText: text,
          detectedLanguage: data.detected_language,
          detectedLanguageName: data.detected_language_name,
          isEnglish: data.is_english,
          translatedText: data.translated_text ?? null,
          translationAvailable: data.translation_available,
          translationError: data.translation_error ?? null,
          finalText: data.translated_text ?? text,
        });
      } catch {
        // ignore silently — user can still type
      } finally {
        setIsDetecting(false);
      }
    },
    [onChange]
  );

  const schedule = (text: string, delay: number) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => detectAndTranslate(text), delay);
  };

  const handleRawChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    // reset detection badges when user edits
    onChange({ ...value, rawText: text, finalText: text, detectedLanguage: null, detectedLanguageName: null, translationError: null });
    schedule(text, 900);
  };

  // onPaste fires BEFORE onChange, so we read from clipboardData directly
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = e.clipboardData.getData("text");
    if (!pasted.trim()) return;
    // Build the full text that will end up in the textarea after paste
    const el = e.currentTarget;
    const before = el.value.slice(0, el.selectionStart ?? 0);
    const after = el.value.slice(el.selectionEnd ?? el.value.length);
    const fullText = before + pasted + after;
    schedule(fullText, 50);
  };

  const handleFinalChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange({ ...value, finalText: e.target.value });
  };

  const translationOk = !value.isEnglish && !!value.translatedText;
  const translationFailed = !value.isEnglish && value.translationAvailable && !value.translatedText && !!value.translationError;
  const noApiKey = !value.isEnglish && !value.translationAvailable && !!value.detectedLanguage;

  const rightLangLabel = value.isEnglish
    ? "English"
    : value.translationAvailable
    ? "English"
    : "English";

  const rightPlaceholder = !value.detectedLanguage
    ? "Translation will appear here…"
    : value.isEnglish
    ? "Already English — edit above"
    : noApiKey
    ? "Add DEEPL_API_KEY to backend .env to enable auto-translation"
    : isDetecting
    ? "Translating…"
    : translationFailed
    ? "Translation failed — see error below"
    : "Translation will appear here…";

  return (
    <div className="cb">
      <div className="cb__title">Client Brief</div>

      <div className="cb__panels">
        {/* ── LEFT: original input ── */}
        <div className="cb__panel cb__panel--left">
          <div className="cb__panel-header">
            <span className="cb__lang-label">
              {isDetecting
                ? "Detecting…"
                : value.detectedLanguageName
                ? value.detectedLanguageName
                : "Original"}
            </span>
            {isDetecting && <span className="cb__spinner" />}
            {!isDetecting && value.isEnglish && value.detectedLanguage && (
              <span className="cb__badge cb__badge--ok">English</span>
            )}
          </div>
          <textarea
            className="cb__textarea"
            placeholder="Paste your client brief here…"
            value={value.rawText}
            onChange={handleRawChange}
            onPaste={handlePaste}
            rows={8}
            spellCheck={false}
          />
        </div>

        {/* ── DIVIDER ── */}
        <div className="cb__divider" aria-hidden>
          <div className="cb__divider-line" />
          <svg className="cb__arrow" viewBox="0 0 24 24" fill="none">
            <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div className="cb__divider-line" />
        </div>

        {/* ── RIGHT: translated / editable ── */}
        <div className="cb__panel cb__panel--right">
          <div className="cb__panel-header">
            <span className={`cb__lang-label ${!value.isEnglish && value.translationAvailable ? "cb__lang-label--en" : ""}`}>
              {rightLangLabel}
            </span>
            {noApiKey && <span className="cb__badge cb__badge--warn">No API key</span>}
            {translationFailed && <span className="cb__badge cb__badge--error">Failed</span>}
          </div>

          <textarea
            className={`cb__textarea cb__textarea--right ${translationOk ? "cb__textarea--translated" : ""}`}
            placeholder={rightPlaceholder}
            value={translationOk ? value.finalText : value.isEnglish ? value.rawText : ""}
            onChange={handleFinalChange}
            readOnly={!translationOk}
            rows={8}
            spellCheck
          />

          {translationOk && (
            <p className="cb__edit-hint">You can edit the translation above before continuing.</p>
          )}
          {translationFailed && (
            <p className="cb__error-hint">
              DeepL error: {value.translationError}
            </p>
          )}
          {noApiKey && (
            <p className="cb__error-hint cb__error-hint--info">
              Add <code>DEEPL_API_KEY</code> to <code>backend/.env</code> to enable automatic translation.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
