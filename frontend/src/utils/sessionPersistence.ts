import type { AuditReport } from "../api/audit";
import type { BriefState } from "../components/ClientBriefInput";
import type { UploadSlotId } from "../types/upload";

/** Keeps the PM's work across a page reload, a dev-server hot reload or a closed
 * tab: the small JSON state (brief, backend session ids, audit reports) lives in
 * localStorage, and the uploaded files themselves -- which later steps re-send to
 * the backend -- live in IndexedDB, since localStorage can't hold a File. Every
 * call is wrapped: storage can be full, blocked or unavailable (private windows),
 * and the app must keep working without it. */

const SESSION_KEY = "pmai.session.v1";
const DB_NAME = "pmai";
const FILES_STORE = "files";

export interface PersistedSession {
  brief: BriefState;
  uploadedSessionIds: Partial<Record<UploadSlotId, string>>;
  plannerSessionId: string | null;
  auditReports: Partial<Record<UploadSlotId, AuditReport>>;
}

export function loadSession(): Partial<PersistedSession> {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as Partial<PersistedSession>) : {};
  } catch {
    return {};
  }
}

export function saveSession(session: PersistedSession): void {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // Storage full or blocked: carry on without persistence.
  }
}

// -- uploaded files (IndexedDB) ----------------------------------------------

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(FILES_STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function loadFiles(): Promise<Partial<Record<UploadSlotId, File>>> {
  try {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const out: Partial<Record<UploadSlotId, File>> = {};
      const request = db.transaction(FILES_STORE, "readonly").objectStore(FILES_STORE).openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) return resolve(out);
        if (cursor.value instanceof File) out[cursor.key as UploadSlotId] = cursor.value;
        cursor.continue();
      };
      request.onerror = () => reject(request.error);
    });
  } catch {
    return {};
  }
}

export async function saveFiles(files: Record<UploadSlotId, File | null>): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(FILES_STORE, "readwrite");
      const store = tx.objectStore(FILES_STORE);
      for (const [slot, file] of Object.entries(files)) {
        if (file) store.put(file, slot);
        else store.delete(slot);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // Same as above: persistence is a convenience, never a requirement.
  }
}

// -- small per-page UI state (e.g. which report slides are ticked) -----------------

export function loadJson<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function saveJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore
  }
}
