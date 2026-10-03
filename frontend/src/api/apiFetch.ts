import { authEnabled, getAccessToken } from "../auth/msal";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function send(path: string, init: RequestInit | undefined, forceRefresh: boolean): Promise<Response> {
  const url = path.startsWith("/") ? `${API_BASE_URL}${path}` : path;
  const token = await getAccessToken(forceRefresh);
  if (!token) return fetch(url, init);
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}

/** fetch() against the backend API; adds the Entra bearer token when auth is enabled. */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const response = await send(path, init, false);
  if (response.status === 401 && authEnabled) {
    return send(path, init, true);
  }
  return response;
}

/** Downloads an API file through apiFetch (so the bearer header is sent) and saves it. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const response = await apiFetch(path);
  if (!response.ok) {
    let detail = `Download failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}
