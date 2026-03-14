import type { FootageManifest } from "../types/manifest";
import type { EditManifest } from "../types/edit-manifest";
import type { EditOperation } from "../types/edit-operations";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.text();
    let message: string;
    try {
      message = JSON.parse(body).error || body;
    } catch {
      message = body;
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export async function fetchManifest(): Promise<FootageManifest> {
  return request<FootageManifest>("/api/manifest");
}

export async function fetchUnitManifest(unitId: string): Promise<FootageManifest> {
  return request<FootageManifest>(`/api/manifest?unit=${encodeURIComponent(unitId)}`);
}

export async function fetchEditManifest(): Promise<EditManifest | null> {
  try {
    return await request<EditManifest>("/api/edit-manifest");
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export async function patchEditManifest(operation: EditOperation): Promise<EditManifest> {
  const result = await request<{ ok: boolean; manifest?: EditManifest; error?: string }>(
    "/api/edit-manifest",
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation }),
    },
  );
  if (!result.ok || !result.manifest) {
    throw new ApiError(400, result.error || "Operation failed");
  }
  return result.manifest;
}

export async function initializeEditManifest(): Promise<EditManifest> {
  const result = await request<{ manifest: EditManifest }>("/api/edit-manifest/init", {
    method: "POST",
  });
  return result.manifest;
}

/** @deprecated Use patchEditManifest instead */
export async function saveEditManifest(
  data: EditManifest,
): Promise<{ ok: boolean; synced_at: string }> {
  return request("/api/edit-manifest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function uploadFile(file: File): Promise<{
  ok: boolean;
  path: string;
  filename: string;
  size: number;
}> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/upload", { method: "POST", body: formData });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: "Upload failed" }));
    throw new ApiError(res.status, (body as Record<string, string>).error || "Upload failed");
  }
  return res.json();
}

export interface TranscriptData {
  clip_id: string;
  engine: string;
  segments: Array<{
    text: string;
    language: string;
    confidence: number;
    start: number;
    end: number;
    words: Array<{
      word: string;
      start: number;
      end: number;
      confidence: number;
    }>;
  }>;
  word_count: number;
  duration_seconds: number;
}

export async function fetchTranscript(clipId: string): Promise<TranscriptData | null> {
  try {
    return await request<TranscriptData>(`/api/transcript/${encodeURIComponent(clipId)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export async function initUnit(
  unitId: string,
  unitType: string,
  displayName: string,
): Promise<{ ok: boolean; unit_dir: string; manifest_path: string }> {
  return request("/api/unit/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ unit_id: unitId, unit_type: unitType, display_name: displayName }),
  });
}

export function mediaUrl(relativePath: string): string {
  return `/api/media/${encodeURIComponent(relativePath).replace(/%2F/g, "/")}`;
}

export function frameUrl(clipId: string, frameName: string): string {
  return `/api/frames/${encodeURIComponent(clipId)}/${encodeURIComponent(frameName)}`;
}

export async function checkHealth(): Promise<boolean> {
  try {
    await request("/api/status");
    return true;
  } catch {
    return false;
  }
}
