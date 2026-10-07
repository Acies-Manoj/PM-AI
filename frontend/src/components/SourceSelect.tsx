import { UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import "./SourceSelect.css";

interface SourceSelectProps {
  files: Record<UploadSlotId, File | null>;
  onSelect: (id: UploadSlotId) => void;
}

export default function SourceSelect({ files, onSelect }: SourceSelectProps) {
  return (
    <div className="source-select">
      <svg className="source-select__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <circle cx="9" cy="9" r="6.5" stroke="currentColor" strokeWidth="1.6" />
        <path d="M14 14L18 18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <select
        className="source-select__input"
        value=""
        onChange={(e) => {
          const id = e.target.value as UploadSlotId;
          if (id) onSelect(id);
          e.target.value = "";
        }}
        aria-label="Jump to a data source"
      >
        <option value="" disabled>
          Jump to a data source…
        </option>
        {UPLOAD_SLOTS.map((slot) => (
          <option key={slot.id} value={slot.id}>
            {slot.title} ({files[slot.id] ? `uploaded: ${files[slot.id]!.name}` : slot.required ? "required, not uploaded" : "optional, not uploaded"})
          </option>
        ))}
      </select>
    </div>
  );
}
