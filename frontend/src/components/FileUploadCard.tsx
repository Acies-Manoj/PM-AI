import { useRef, useState } from "react";
import type { DragEvent } from "react";
import type { UploadSlotConfig } from "../types/upload";
import "./FileUploadCard.css";

interface FileUploadCardProps {
  config: UploadSlotConfig;
  file: File | null;
  error?: string;
  highlighted?: boolean;
  /** Skips the built-in title/badge/description header -- for callers that
   * build their own (e.g. OutlierCorrectionStep, which puts action buttons
   * in that same header row). */
  hideHeader?: boolean;
  /** Shrinks the dropzone/card -- for callers where this isn't the primary
   * upload control on the page (e.g. OutlierCorrectionStep's re-upload). */
  compact?: boolean;
  onSelect: (file: File) => void;
  onRemove: () => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FileUploadCard({ config, file, error, highlighted, hideHeader, compact, onSelect, onRemove }: FileUploadCardProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onSelect(dropped);
  };

  const handleBrowseClick = () => inputRef.current?.click();

  const status: "empty" | "selected" | "error" = error ? "error" : file ? "selected" : "empty";

  return (
    <div
      className={`upload-card upload-card--${status} ${highlighted ? "upload-card--highlighted" : ""} ${compact ? "upload-card--compact" : ""}`}
    >
      {!hideHeader && (
        <div className="upload-card__header">
          <h3 className="upload-card__title">
            {config.title}
            {config.required ? (
              <span className="upload-card__badge upload-card__badge--required">Required</span>
            ) : (
              <span className="upload-card__badge upload-card__badge--optional">Optional</span>
            )}
          </h3>
          <p className="upload-card__description">{config.description}</p>
        </div>
      )}

      <div className="upload-card__body">
        {!file ? (
          <div
            className={`upload-card__dropzone ${isDragOver ? "upload-card__dropzone--active" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={() => setIsDragOver(false)}
            onDrop={handleDrop}
            onClick={handleBrowseClick}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") handleBrowseClick();
            }}
          >
            <svg className="upload-card__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 4v11m0-11 4 4m-4-4-4 4M5 16.5V18a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-1.5"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <p className="upload-card__dropzone-text">
              <span className="upload-card__link">Click to browse</span> or drag a file here
            </p>
            <p className="upload-card__accept-label">{config.acceptLabel}</p>
            <input
              ref={inputRef}
              type="file"
              accept={config.accept}
              className="upload-card__input"
              onChange={(e) => {
                const selected = e.target.files?.[0];
                if (selected) onSelect(selected);
                e.target.value = "";
              }}
            />
          </div>
        ) : (
          <div className="upload-card__file">
            <svg className="upload-card__file-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
              />
              <path d="M14 3v5h5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            </svg>
            <div className="upload-card__file-info">
              <span className="upload-card__file-name" title={file.name}>
                {file.name}
              </span>
              <span className="upload-card__file-size">{formatBytes(file.size)}</span>
            </div>
            <button
              type="button"
              className="upload-card__remove"
              onClick={onRemove}
              aria-label={`Remove ${file.name}`}
            >
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M5 5l10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        )}

        {error && <p className="upload-card__error">{error}</p>}
        {!error && file && <p className="upload-card__success">Ready to upload</p>}
      </div>
    </div>
  );
}
