import type { BriefState } from "../components/ClientBriefInput";
import type { FilesState } from "../App";
import { UPLOAD_SLOTS } from "../constants/uploadSlots";

import { apiFetch } from "./apiFetch";

export interface SessionMetadata {
  session_id: string;
}

export async function finalizeBrief(
  brief: BriefState,
  files: FilesState,
  auditSessionIds: string[]
): Promise<SessionMetadata> {
  const fileEntries = UPLOAD_SLOTS.filter((s) => files[s.id]).map((s) => {
    const f = files[s.id]!;
    return {
      slot: s.id,
      filename: f.name,
      size: f.size,
      mime_type: f.type || "application/octet-stream",
    };
  });

  const body = {
    audit_session_ids: auditSessionIds,
    raw_brief: brief.rawText,
    final_brief: brief.finalText,
    original_language: brief.detectedLanguage,
    original_language_name: brief.detectedLanguageName,
    translated_text: brief.translatedText,
    files: fileEntries,
  };

  const res = await apiFetch(`/api/brief/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Finalize failed: ${res.status} ${text}`);
  }

  return res.json() as Promise<SessionMetadata>;
}
