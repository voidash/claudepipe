import { Router, Request, Response } from "express";
import {
  readManifest,
  readUnitManifest,
  readEditManifest,
  writeEditManifest,
  atomicEditManifestUpdate,
  editManifestExists,
  readTranscript,
  initializeUnit,
} from "../lib/project.js";
import { applyOperation } from "../../src/lib/apply-operation.js";
import { buildEditManifestFromFootage } from "../../src/lib/manifest-utils.js";
import type { EditManifest } from "../../src/types/edit-manifest.js";
import type { EditOperation } from "../../src/types/edit-operations.js";
import type { FootageManifest } from "../../src/types/manifest.js";

const router = Router();

router.get("/manifest", async (_req: Request, res: Response) => {
  try {
    const unitId = _req.query.unit as string | undefined;
    if (unitId) {
      const data = await readUnitManifest(unitId);
      res.json(data);
    } else {
      const data = await readManifest();
      res.json(data);
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    if (message.includes("ENOENT")) {
      res.status(404).json({ error: "Manifest not found" });
    } else {
      res.status(500).json({ error: message });
    }
  }
});

router.get("/edit-manifest", async (_req: Request, res: Response) => {
  try {
    if (!editManifestExists()) {
      res.status(404).json({ error: "Edit manifest not found (first run)" });
      return;
    }
    const data = await readEditManifest();
    res.json(data);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

// DEPRECATED: Full-document POST. Use PATCH with operations instead.
router.post("/edit-manifest", async (req: Request, res: Response) => {
  console.warn("[DEPRECATED] POST /api/edit-manifest called — migrate to PATCH /api/edit-manifest with operations");
  try {
    const data = req.body;
    if (!data || typeof data !== "object") {
      res.status(400).json({ error: "Invalid JSON body" });
      return;
    }
    await writeEditManifest(data);
    res.json({ ok: true, synced_at: new Date().toISOString() });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

// Operation-based mutation — atomically reads manifest, applies op, writes back.
// The entire read-apply-write is serialized via a queue — no interleaving between concurrent requests.
router.patch("/edit-manifest", async (req: Request, res: Response) => {
  try {
    const { operation } = req.body as { operation?: EditOperation };
    if (!operation || typeof operation !== "object" || !operation.type) {
      res.status(400).json({ ok: false, error: "Missing or invalid operation" });
      return;
    }

    if (!editManifestExists()) {
      res.status(404).json({ ok: false, error: "Edit manifest not found — call POST /api/edit-manifest/init first" });
      return;
    }

    const updated = await atomicEditManifestUpdate<EditManifest | { error: string }>((current) => {
      const result = applyOperation(current as EditManifest, operation);
      if (!result.ok) {
        return { data: current, result: { error: result.error }, write: false };
      }
      const manifest = { ...result.manifest, last_synced: new Date().toISOString() };
      return { data: manifest, result: manifest };
    });

    if ("error" in updated) {
      res.status(400).json({ ok: false, error: updated.error });
      return;
    }

    res.json({ ok: true, manifest: updated });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ ok: false, error: message });
  }
});

// Initialize edit manifest — creates from footage manifest if doesn't exist, returns existing if it does
router.post("/edit-manifest/init", async (_req: Request, res: Response) => {
  try {
    if (editManifestExists()) {
      const existing = await readEditManifest() as EditManifest;
      res.json({ manifest: existing });
      return;
    }
    const footageManifest = await readManifest() as FootageManifest;
    const fresh = buildEditManifestFromFootage(footageManifest);
    await writeEditManifest(fresh);
    res.json({ manifest: fresh });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

router.get("/transcript/:clipId", async (req: Request, res: Response) => {
  try {
    const clipId = Array.isArray(req.params.clipId) ? req.params.clipId[0] : req.params.clipId;
    const data = await readTranscript(clipId);
    res.json(data);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    if (message.includes("ENOENT")) {
      res.status(404).json({ error: "Transcript not found" });
    } else {
      res.status(500).json({ error: message });
    }
  }
});

router.post("/unit/init", async (req: Request, res: Response) => {
  try {
    const { unit_id, unit_type, display_name } = req.body as {
      unit_id?: string;
      unit_type?: string;
      display_name?: string;
    };

    if (!unit_id || !unit_type || !display_name) {
      res.status(400).json({ error: "Missing required fields: unit_id, unit_type, display_name" });
      return;
    }

    const { unitDir, manifestPath } = await initializeUnit(unit_id, unit_type, display_name);
    res.json({ ok: true, unit_dir: unitDir, manifest_path: manifestPath });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

router.get("/status", (_req: Request, res: Response) => {
  res.json({ status: "ok", timestamp: new Date().toISOString() });
});

export default router;
