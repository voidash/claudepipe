import { Router, Request, Response } from "express";
import path from "path";
import fs from "fs/promises";
import { existsSync, statSync } from "fs";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);
const router = Router();

const MEDIA_EXTENSIONS = new Set([
  ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".insv", ".insp", ".lrv",
  ".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a",
  ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".cr2", ".arw", ".dng", ".nef", ".heic",
  ".txt", ".md", ".srt", ".vtt", ".json",
]);

// Hidden/system dirs to skip
const SKIP_DIRS = new Set([
  ".Spotlight-V100", ".fseventsd", ".Trashes", ".TemporaryItems",
  "System Volume Information", "$RECYCLE.BIN", ".DS_Store",
]);

function isHidden(name: string): boolean {
  return name.startsWith(".") && name !== "..";
}

// List directory contents
router.get("/fs/list", async (req: Request, res: Response) => {
  try {
    const dirPath = (req.query.path as string) || "/";
    const showHidden = req.query.hidden === "true";

    const resolved = path.resolve(dirPath);
    if (!existsSync(resolved)) {
      res.status(404).json({ error: "Directory not found" });
      return;
    }

    const stat = statSync(resolved);
    if (!stat.isDirectory()) {
      res.status(400).json({ error: "Not a directory" });
      return;
    }

    const entries = await fs.readdir(resolved, { withFileTypes: true });
    const results = [];

    for (const entry of entries) {
      if (SKIP_DIRS.has(entry.name)) continue;
      if (!showHidden && isHidden(entry.name)) continue;

      const fullPath = path.join(resolved, entry.name);
      try {
        const entryStat = statSync(fullPath);
        const ext = path.extname(entry.name).toLowerCase();

        // For files, only show media/text files
        if (entry.isFile() && !MEDIA_EXTENSIONS.has(ext)) continue;

        results.push({
          name: entry.name,
          path: fullPath,
          type: entry.isDirectory() ? "directory" : entry.isSymbolicLink() ? "symlink" : "file",
          size: entryStat.size,
          modified: entryStat.mtime.toISOString(),
          extension: ext,
        });
      } catch {
        // Skip entries we can't stat (permission issues)
      }
    }

    // Sort: directories first, then alphabetical
    results.sort((a, b) => {
      if (a.type === "directory" && b.type !== "directory") return -1;
      if (a.type !== "directory" && b.type === "directory") return 1;
      return a.name.localeCompare(b.name);
    });

    res.json({
      path: resolved,
      parent: path.dirname(resolved),
      entries: results,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

// Probe a media file with ffprobe
router.get("/fs/probe", async (req: Request, res: Response) => {
  try {
    const filePath = req.query.path as string;
    if (!filePath) {
      res.status(400).json({ error: "path required" });
      return;
    }

    const resolved = path.resolve(filePath);
    if (!existsSync(resolved)) {
      res.status(404).json({ error: "File not found" });
      return;
    }

    const { stdout } = await execFileAsync("ffprobe", [
      "-v", "quiet",
      "-print_format", "json",
      "-show_format", "-show_streams",
      resolved,
    ], { timeout: 10000 });

    const probe = JSON.parse(stdout);
    const videoStream = probe.streams?.find((s: any) => s.codec_type === "video");
    const audioStream = probe.streams?.find((s: any) => s.codec_type === "audio");
    const format = probe.format || {};

    const fpsStr = videoStream?.r_frame_rate || "30/1";
    const fpsParts = fpsStr.split("/");
    const fps = fpsParts.length === 2 ? parseInt(fpsParts[0]) / parseInt(fpsParts[1]) : parseFloat(fpsStr);

    res.json({
      duration_seconds: parseFloat(format.duration || "0"),
      width: videoStream ? parseInt(videoStream.width || "0") : 0,
      height: videoStream ? parseInt(videoStream.height || "0") : 0,
      fps: Math.round(fps * 100) / 100,
      codec_video: videoStream?.codec_name || "",
      codec_audio: audioStream?.codec_name || "",
      has_audio: !!audioStream,
      camera_model: format.tags?.com_apple_quicktime_model || format.tags?.model || "",
      creation_time: format.tags?.creation_time || "",
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

// Detect camera folder structure
router.get("/fs/detect-camera", async (req: Request, res: Response) => {
  try {
    const dirPath = (req.query.path as string) || "/";
    const resolved = path.resolve(dirPath);

    if (!existsSync(resolved)) {
      res.status(404).json({ error: "Directory not found" });
      return;
    }

    const detections: any[] = [];

    // Check for DCIM (standard camera folder)
    const dcimPath = path.join(resolved, "DCIM");
    if (existsSync(dcimPath)) {
      const dcimEntries = await fs.readdir(dcimPath, { withFileTypes: true });

      for (const entry of dcimEntries) {
        if (!entry.isDirectory()) continue;
        const subDir = entry.name;
        const subPath = path.join(dcimPath, subDir);

        let cameraType: string | null = null;
        let label = "";

        // GoPro: 100GOPRO, 101GOPRO, etc.
        if (/^\d{3}GOPRO$/i.test(subDir)) {
          cameraType = "gopro";
          label = `GoPro (${subDir})`;
        }
        // Canon: 100CANON, 101CANON, etc.
        else if (/^\d{3}CANON$/i.test(subDir) || /^\d{3}EOS$/i.test(subDir)) {
          cameraType = "canon";
          label = `Canon (${subDir})`;
        }
        // Pixel/Android: Camera folder
        else if (/^Camera$/i.test(subDir)) {
          cameraType = "pixel";
          label = "Pixel / Android Camera";
        }
        // Insta360
        else if (/insta360/i.test(subDir) || /^Camera\d{2}$/i.test(subDir)) {
          cameraType = "insta360";
          label = `Insta360 (${subDir})`;
        }

        if (cameraType) {
          const files = await scanMediaFiles(subPath);
          if (files.length > 0) {
            detections.push({
              camera_type: cameraType,
              label,
              files,
              total_count: files.length,
              total_size_bytes: files.reduce((s, f) => s + f.size, 0),
              total_duration_seconds: 0, // Would need ffprobe for each, skip for speed
            });
          }
        }
      }
    }

    // Check for Insta360 root-level folders
    const insta360Patterns = ["Insta360OneX2", "Insta360OneRS", "Insta360OneR", "Insta360GO"];
    for (const pattern of insta360Patterns) {
      const instaPath = path.join(resolved, pattern);
      if (existsSync(instaPath)) {
        const files = await scanMediaFiles(instaPath);
        if (files.length > 0) {
          detections.push({
            camera_type: "insta360",
            label: pattern,
            files,
            total_count: files.length,
            total_size_bytes: files.reduce((s, f) => s + f.size, 0),
            total_duration_seconds: 0,
          });
        }
      }
    }

    // If no specific camera detected but DCIM exists with media files, treat as generic
    if (detections.length === 0 && existsSync(dcimPath)) {
      const files = await scanMediaFilesRecursive(dcimPath);
      if (files.length > 0) {
        detections.push({
          camera_type: "generic",
          label: "Camera (DCIM)",
          files,
          total_count: files.length,
          total_size_bytes: files.reduce((s, f) => s + f.size, 0),
          total_duration_seconds: 0,
        });
      }
    }

    res.json({ detections });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

async function scanMediaFiles(dirPath: string): Promise<any[]> {
  const results: any[] = [];
  try {
    const entries = await fs.readdir(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      const ext = path.extname(entry.name).toLowerCase();
      // Skip GoPro thumbnails and low-res previews
      if ([".thm", ".lrv"].includes(ext)) continue;
      if (!MEDIA_EXTENSIONS.has(ext)) continue;

      const fullPath = path.join(dirPath, entry.name);
      const stat = statSync(fullPath);
      results.push({
        path: fullPath,
        name: entry.name,
        size: stat.size,
        extension: ext,
      });
    }
  } catch {
    // Permission denied, skip
  }
  return results;
}

async function scanMediaFilesRecursive(dirPath: string): Promise<any[]> {
  const results: any[] = [];
  try {
    const entries = await fs.readdir(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      if (entry.isDirectory()) {
        results.push(...(await scanMediaFilesRecursive(fullPath)));
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name).toLowerCase();
        if ([".thm", ".lrv"].includes(ext)) continue;
        if (!MEDIA_EXTENSIONS.has(ext)) continue;
        const stat = statSync(fullPath);
        results.push({ path: fullPath, name: entry.name, size: stat.size, extension: ext });
      }
    }
  } catch {
    // Permission denied, skip
  }
  return results;
}

export default router;
