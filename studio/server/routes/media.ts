import { Router, Request, Response } from "express";
import path from "path";
import { createReadStream, existsSync, statSync } from "fs";
import { resolvePath } from "../lib/project.js";

const router = Router();

// Serve media files with Range support for video seeking
// Express 5 wildcard: *name captures the rest of the path
router.get("/media/*filepath", (req: Request, res: Response) => {
  try {
    const rawPath = req.params.filepath;
    const relativePath = Array.isArray(rawPath) ? rawPath.join("/") : String(rawPath);
    if (!relativePath) {
      res.status(400).json({ error: "No path specified" });
      return;
    }

    const filePath = resolvePath(relativePath);
    if (!existsSync(filePath)) {
      res.status(404).json({ error: "File not found" });
      return;
    }

    const stat = statSync(filePath);
    const fileSize = stat.size;
    const ext = path.extname(filePath).toLowerCase();

    const mimeTypes: Record<string, string> = {
      ".mp4": "video/mp4",
      ".webm": "video/webm",
      ".mov": "video/quicktime",
      ".mkv": "video/x-matroska",
      ".avi": "video/x-msvideo",
      ".wav": "audio/wav",
      ".mp3": "audio/mpeg",
      ".aac": "audio/aac",
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".webp": "image/webp",
    };

    const contentType = mimeTypes[ext] || "application/octet-stream";
    const range = req.headers.range;

    if (range) {
      const parts = range.replace(/bytes=/, "").split("-");
      const start = parseInt(parts[0], 10);
      const end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;
      const chunkSize = end - start + 1;

      res.writeHead(206, {
        "Content-Range": `bytes ${start}-${end}/${fileSize}`,
        "Accept-Ranges": "bytes",
        "Content-Length": chunkSize,
        "Content-Type": contentType,
      });

      createReadStream(filePath, { start, end }).pipe(res);
    } else {
      res.writeHead(200, {
        "Content-Length": fileSize,
        "Content-Type": contentType,
        "Accept-Ranges": "bytes",
      });

      createReadStream(filePath).pipe(res);
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

// Serve extracted frames
router.get("/frames/:clipId/:idx", async (req: Request, res: Response) => {
  try {
    const { clipId, idx } = req.params;
    const safeClipId = String(clipId).replace(/[^a-zA-Z0-9_-]/g, "");
    const safeIdx = String(idx).replace(/[^a-zA-Z0-9_.-]/g, "");

    const framePath = resolvePath(path.join("frames", safeClipId, safeIdx));
    if (!existsSync(framePath)) {
      res.status(404).json({ error: "Frame not found" });
      return;
    }

    const ext = path.extname(framePath).toLowerCase();
    const ct = ext === ".png" ? "image/png" : "image/jpeg";
    res.setHeader("Content-Type", ct);
    res.setHeader("Cache-Control", "public, max-age=86400");
    createReadStream(framePath).pipe(res);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

export default router;
