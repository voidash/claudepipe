import path from "path";
import fs from "fs/promises";
import { existsSync, readdirSync } from "fs";

const PROJECT_ROOT = process.env.PROJECT_ROOT;

// PROJECT_ROOT is optional — when not set, we're in import mode
export const projectRoot: string | null = PROJECT_ROOT
  ? path.resolve(PROJECT_ROOT)
  : null;

export const isImportMode = projectRoot === null;

if (projectRoot && !existsSync(projectRoot)) {
  console.error(`ERROR: PROJECT_ROOT does not exist: ${PROJECT_ROOT}`);
  process.exit(1);
}

export function requireProjectRoot(): string {
  if (!projectRoot) {
    throw new Error("PROJECT_ROOT not set — this endpoint requires an existing project");
  }
  return projectRoot;
}

export function resolvePath(relativePath: string): string {
  const root = requireProjectRoot();
  const resolved = path.resolve(root, relativePath);
  if (!resolved.startsWith(root)) {
    throw new Error(`Path traversal blocked: ${relativePath}`);
  }
  return resolved;
}

export async function readManifest(): Promise<unknown> {
  const root = requireProjectRoot();
  const manifestPath = path.join(root, "footage_manifest.json");
  const data = await fs.readFile(manifestPath, "utf-8");
  return JSON.parse(data);
}

export async function readUnitManifest(unitId: string): Promise<unknown> {
  const root = requireProjectRoot();
  const safeName = unitId.replace(/[^a-zA-Z0-9_-]/g, "");
  const unitDir = path.join(root, "units", safeName);
  if (!unitDir.startsWith(root)) {
    throw new Error("Path traversal blocked");
  }
  const manifestPath = path.join(unitDir, "footage_manifest.json");
  const data = await fs.readFile(manifestPath, "utf-8");
  const parsed = JSON.parse(data);

  // Fix symlink_path mismatches: unit manifests may reference original source
  // filenames (e.g. "raw/GX012467.MP4") but the actual symlinks in the unit
  // directory use clip IDs (e.g. "raw/clip_2467.MP4"). Build a lookup from
  // what's actually on disk and correct the paths before serving.
  fixSymlinkPaths(parsed, unitDir);

  // Unit manifests store paths relative to the unit directory (e.g. "raw/file.mov").
  // The media server resolves paths relative to PROJECT_ROOT.
  // Rewrite all unit-relative paths to PROJECT_ROOT-relative paths so the
  // client can use them directly without knowing about unit directory nesting.
  const unitPrefix = `units/${safeName}/`;
  const pathPrefixes = ["raw/", "audio/", "frames/", "analysis/"];
  rewriteUnitPaths(parsed, unitPrefix, pathPrefixes);

  return parsed;
}

/**
 * Fix symlink_path values in clips when the manifest references a filename
 * that doesn't exist in the unit's raw/ directory. Looks up the actual file
 * by matching the clip ID (e.g. clip_2467 → raw/clip_2467.MP4).
 */
function fixSymlinkPaths(manifest: unknown, unitDir: string): void {
  if (!manifest || typeof manifest !== "object") return;
  const m = manifest as Record<string, unknown>;
  const clips = m.clips;
  if (!Array.isArray(clips)) return;

  const rawDir = path.join(unitDir, "raw");
  let actualFiles: string[];
  try {
    actualFiles = readdirSync(rawDir);
  } catch {
    return; // no raw/ directory — nothing to fix
  }

  const actualSet = new Set(actualFiles);

  for (const clip of clips) {
    if (!clip || typeof clip !== "object") continue;
    const c = clip as Record<string, unknown>;
    const symlinkPath = c.symlink_path;
    if (typeof symlinkPath !== "string" || !symlinkPath.startsWith("raw/")) continue;

    const manifestFilename = path.basename(symlinkPath);
    if (actualSet.has(manifestFilename)) continue; // file exists, no fix needed

    // Try to find by clip ID: clip.id = "clip_2467" → look for "clip_2467.*" in raw/
    const clipId = typeof c.id === "string" ? c.id : null;
    if (!clipId) continue;

    const match = actualFiles.find((f) => {
      const stem = f.replace(/\.[^.]+$/, "");
      return stem === clipId;
    });

    if (match) {
      c.symlink_path = `raw/${match}`;
    }
  }
}

/**
 * Walk a JSON value and prefix any string that starts with a known
 * path prefix (raw/, audio/, frames/, analysis/) — unless it's already
 * prefixed with the unit path. Mutates in place.
 */
function rewriteUnitPaths(
  obj: unknown,
  unitPrefix: string,
  pathPrefixes: string[],
): void {
  if (obj == null || typeof obj !== "object") return;

  if (Array.isArray(obj)) {
    for (let i = 0; i < obj.length; i++) {
      const v = obj[i];
      if (typeof v === "string" && needsPrefix(v, unitPrefix, pathPrefixes)) {
        obj[i] = unitPrefix + v;
      } else if (typeof v === "object" && v != null) {
        rewriteUnitPaths(v, unitPrefix, pathPrefixes);
      }
    }
    return;
  }

  for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
    if (typeof val === "string" && needsPrefix(val, unitPrefix, pathPrefixes)) {
      (obj as Record<string, unknown>)[key] = unitPrefix + val;
    } else if (typeof val === "object" && val != null) {
      rewriteUnitPaths(val, unitPrefix, pathPrefixes);
    }
  }
}

function needsPrefix(val: string, unitPrefix: string, pathPrefixes: string[]): boolean {
  if (val.startsWith(unitPrefix)) return false;
  return pathPrefixes.some((p) => val.startsWith(p));
}

export async function readEditManifest(): Promise<unknown> {
  const root = requireProjectRoot();
  const editPath = path.join(root, "edit_manifest.json");
  const data = await fs.readFile(editPath, "utf-8");
  return JSON.parse(data);
}

// Serialize all edit manifest I/O — prevents concurrent requests from
// interleaving reads and writes, which causes lost updates and ENOENT on .tmp rename.
let editManifestQueue: Promise<unknown> = Promise.resolve();

function enqueue<T>(fn: () => Promise<T>): Promise<T> {
  const p = editManifestQueue.then(fn, fn);
  // Update the queue tail. Cast because the queue tracks the chain, not the result type.
  editManifestQueue = p.then(() => {}, () => {});
  return p as Promise<T>;
}

export async function writeEditManifest(data: unknown): Promise<void> {
  return enqueue(async () => {
    const root = requireProjectRoot();
    const editPath = path.join(root, "edit_manifest.json");
    const tmpPath = editPath + ".tmp";
    await fs.writeFile(tmpPath, JSON.stringify(data, null, 2), "utf-8");
    await fs.rename(tmpPath, editPath);
  });
}

/**
 * Atomically read the edit manifest, apply a transform, and write it back.
 * The entire read-transform-write cycle is serialized — no interleaving.
 * If transform returns `write: false`, the file is not written (used for validation errors).
 */
export async function atomicEditManifestUpdate<T>(
  transform: (current: unknown) => { data: unknown; result: T; write?: boolean },
): Promise<T> {
  return enqueue(async () => {
    const root = requireProjectRoot();
    const editPath = path.join(root, "edit_manifest.json");
    const raw = await fs.readFile(editPath, "utf-8");
    const current = JSON.parse(raw);
    const { data, result, write = true } = transform(current);
    if (write) {
      const tmpPath = editPath + ".tmp";
      await fs.writeFile(tmpPath, JSON.stringify(data, null, 2), "utf-8");
      await fs.rename(tmpPath, editPath);
    }
    return result;
  });
}

export function editManifestExists(): boolean {
  if (!projectRoot) return false;
  return existsSync(path.join(projectRoot, "edit_manifest.json"));
}

export async function initializeUnit(
  unitId: string,
  unitType: string,
  displayName: string,
): Promise<{ unitDir: string; manifestPath: string }> {
  const root = requireProjectRoot();
  const safeName = unitId.replace(/[^a-zA-Z0-9_-]/g, "");
  if (!safeName) {
    throw new Error("Invalid unit ID after sanitization");
  }
  const unitDir = path.join(root, "units", safeName);
  if (!unitDir.startsWith(root)) {
    throw new Error("Path traversal blocked");
  }

  // If directory already exists, return success (idempotent)
  if (existsSync(unitDir)) {
    const manifestPath = path.join(unitDir, "footage_manifest.json");
    return { unitDir, manifestPath };
  }

  // Create unit directory structure
  const subdirs = ["raw", "audio", "frames", path.join("analysis", "transcripts")];
  for (const sub of subdirs) {
    await fs.mkdir(path.join(unitDir, sub), { recursive: true });
  }

  // Write minimal footage_manifest.json
  const manifest = {
    version: "1.0.0",
    project: {
      id: path.basename(root),
      root_dir: root,
    },
    clips: [],
    timeline: {
      segments: [],
      order: [],
      transitions: [],
      total_duration_seconds: 0,
    },
    units: [
      {
        unit_id: safeName,
        type: unitType,
        display_name: displayName,
        activity: "",
        clip_ids: [],
        duration_seconds: 0,
        segment_count: 0,
      },
    ],
    pipeline_state: {
      current_phase: 0,
      completed_phases: [],
      failed_phases: [],
      skipped_phases: [],
    },
  };

  const manifestPath = path.join(unitDir, "footage_manifest.json");
  await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2), "utf-8");

  return { unitDir, manifestPath };
}

export async function readTranscript(clipId: string): Promise<unknown> {
  const root = requireProjectRoot();
  const safeClipId = clipId.replace(/[^a-zA-Z0-9_-]/g, "");
  const transcriptsDir = path.join(root, "analysis", "transcripts");

  // Build candidate filenames to try
  const candidates = [safeClipId];

  // Strip "added_" prefix → try with "clip_" prefix
  if (safeClipId.startsWith("added_")) {
    const stem = safeClipId.slice(6);
    candidates.push(`clip_${stem}`);
    // Also strip _edited/_trimmed suffixes
    const cleanStem = stem.replace(/_(edited|trimmed|cut|processed)$/, "");
    if (cleanStem !== stem) candidates.push(`clip_${cleanStem}`);
  }

  for (const candidate of candidates) {
    const transcriptPath = path.join(transcriptsDir, `${candidate}.json`);
    if (!transcriptPath.startsWith(root)) continue;
    try {
      const data = await fs.readFile(transcriptPath, "utf-8");
      return JSON.parse(data);
    } catch {
      // try next candidate
    }
  }
  throw new Error(`ENOENT: transcript not found for ${clipId}`);
}
