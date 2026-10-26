// Typed client for the Yatta API (/api/v1). Types are generated from the backend's OpenAPI schema (npm run gen:api).
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Avatar = Schemas["Avatar"];
export type Variant = Schemas["Variant"];
export type Voice = Schemas["Voice"];
export type VoiceCatalogue = Schemas["VoiceCatalogue"];
export type Render = Schemas["Render"];
export type Status = Schemas["Status"];
export type Training = Schemas["Training"];
export type Quick = Schemas["Quick"];
export type Upload = Schemas["Upload"];
export type Background = Schemas["Background"];
export type RenderCreate = Schemas["RenderCreate"];

export const api = createClient<paths>({ baseUrl: "" });

// Every state-changing request carries X-Yatta (a cross-site form cannot); a 401 means the session ended.
api.use({
  onRequest({ request }) {
    request.headers.set("X-Yatta", "1");
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401 && !response.url.endsWith("/api/v1/session")) window.dispatchEvent(new Event("yatta:signed-out"));
    return response;
  },
});

/** Unwrap an openapi-fetch result, turning API errors into thrown Errors with the server's message. */
export async function call<T>(promise: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || !response.ok) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    throw new Error(typeof detail === "string" ? detail : `${response.status} ${response.statusText}`);
  }
  return data as T;
}

function putChunk(url: string, blob: Blob, onProgress: (loaded: number) => void) {
  return new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.setRequestHeader("X-Yatta", "1");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded);
    xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new Error(safeDetail(xhr.responseText) || `Upload failed (${xhr.status})`)));
    xhr.onerror = () => reject(new Error("connection lost"));
    xhr.send(blob);
  });
}

function safeDetail(text: string) {
  try { return JSON.parse(text).detail as string; } catch { return ""; }
}

/** Upload a file in 32 MB chunks (Cloudflare caps request bodies at 100 MB), retrying a failed chunk a few times. */
export async function uploadFile(file: File, kind: "video" | "audio" | "background", onProgress?: (fraction: number) => void): Promise<Upload> {
  const ticket = await call(api.POST("/api/v1/uploads", { body: { kind, name: file.name || kind, size: file.size } }));
  const size = Math.min(32 * 1024 * 1024, ticket.chunk_limit);
  for (let offset = 0; offset < file.size; offset += size) {
    const blob = file.slice(offset, offset + size);
    for (let attempt = 1; ; attempt++) {
      try {
        await putChunk(`/api/v1/uploads/${ticket.id}?offset=${offset}`, blob, (loaded) => onProgress?.((offset + loaded) / file.size));
        break;
      } catch (error) {
        if (attempt >= 4) throw new Error(`Upload failed: ${(error as Error).message}`);
        await new Promise((r) => setTimeout(r, 1500 * attempt));
      }
    }
  }
  return call(api.POST("/api/v1/uploads/{upload_id}/finish", { params: { path: { upload_id: ticket.id } } }));
}
