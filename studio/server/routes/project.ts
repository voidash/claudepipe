import { Router, Request, Response } from "express";
import path from "path";
import { fileURLToPath } from "url";
import fs from "fs/promises";
import { existsSync, mkdirSync } from "fs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const router = Router();

const PROJECT_DIRS = [
  "raw", "audio/denoised", "frames", "sfx", "music", "animations",
  "thumbnails", "blender", "exports", "units", "tmp",
  "analysis/transcripts", "analysis/vad", "analysis/pitch",
  "analysis/scenes", "analysis/yolo", "analysis/vision",
];

router.post("/project/create", async (req: Request, res: Response) => {
  try {
    const { project_dir, hint, files } = req.body;

    if (!project_dir || !files || !Array.isArray(files) || files.length === 0) {
      res.status(400).json({ error: "project_dir and files[] required" });
      return;
    }

    const projectRoot = path.resolve(project_dir);

    // Create project directory
    if (!existsSync(projectRoot)) {
      mkdirSync(projectRoot, { recursive: true });
    }

    // Create subdirectories
    for (const dir of PROJECT_DIRS) {
      const fullDir = path.join(projectRoot, dir);
      if (!existsSync(fullDir)) {
        mkdirSync(fullDir, { recursive: true });
      }
    }

    // Symlink source files into raw/
    const sourceFiles: string[] = [];
    const importantFiles: string[] = [];

    for (const file of files) {
      const sourcePath = path.resolve(file.path);
      if (!existsSync(sourcePath)) {
        continue;
      }

      sourceFiles.push(sourcePath);
      if (file.important) {
        importantFiles.push(sourcePath);
      }

      const baseName = path.basename(sourcePath);
      const linkPath = path.join(projectRoot, "raw", baseName);

      // Handle name collisions
      let finalLinkPath = linkPath;
      let counter = 1;
      while (existsSync(finalLinkPath)) {
        const ext = path.extname(baseName);
        const name = path.basename(baseName, ext);
        finalLinkPath = path.join(projectRoot, "raw", `${name}_${counter}${ext}`);
        counter++;
      }

      try {
        await fs.symlink(sourcePath, finalLinkPath);
      } catch (err) {
        // If symlink fails (e.g., cross-device), copy instead
        await fs.copyFile(sourcePath, finalLinkPath);
      }
    }

    // Copy style_config_default.json if it exists in the skill templates
    // The skill will handle this, but we provide a minimal one
    const styleConfigPath = path.join(projectRoot, "style_config.json");
    if (!existsSync(styleConfigPath)) {
      // Try to find the template
      const templatePaths = [
        path.join(process.cwd(), "../.claude/skills/footage/templates/style_config_default.json"),
        path.join(__dirname, "../../../.claude/skills/footage/templates/style_config_default.json"),
      ];
      let copied = false;
      for (const tp of templatePaths) {
        if (existsSync(tp)) {
          await fs.copyFile(tp, styleConfigPath);
          copied = true;
          break;
        }
      }
      if (!copied) {
        // Write minimal style config
        await fs.writeFile(styleConfigPath, JSON.stringify({
          version: "1.0.0",
          colors: {
            primary: "#FF6B35", secondary: "#004E89", accent: "#F7C948",
            background: "#1A1A2E", text: "#FFFFFF", text_secondary: "#B8B8D0",
            success: "#2ECC71", warning: "#F39C12", error: "#E74C3C",
          },
        }, null, 2));
      }
    }

    // Initialize footage_manifest.json
    const now = new Date().toISOString();
    const projectId = `footage_project_${Date.now()}`;
    const manifest = {
      version: "1.0.0",
      project: {
        id: projectId,
        created: now,
        root_dir: projectRoot,
        hint: hint || "",
        source_files: sourceFiles,
        important_files: importantFiles,
      },
      clips: [],
      timeline: { segments: [], order: [], transitions: [], total_duration_seconds: 0 },
      units: [],
      sfx: [],
      music: { tracks: [] },
      animations: [],
      thumbnails: [],
      outputs: {
        long_16_9: { blender_path: "", fcpxml_path: "", resolution: { w: 1920, h: 1080 }, fps: 30, render_path: null, render_status: "pending" },
        long_9_16: { blender_path: "", fcpxml_path: "", resolution: { w: 1080, h: 1920 }, fps: 30, render_path: null, render_status: "pending" },
        shorts: [],
      },
      youtube: {
        long_form: {
          title: "", description: "", tags: [], category_id: 28,
          default_language: "ne", default_audio_language: "ne", privacy: "private",
          chapters: [], cards: [], end_screen: {},
        },
        shorts: [],
      },
      pipeline_state: {
        current_phase: 0,
        completed_phases: [],
        phase_results: {},
        errors: [],
        warnings: [],
        units_decomposed: false,
        units_decomposed_at: null,
        units_merged: false,
        units_merged_at: null,
        last_updated: now,
      },
    };

    const manifestPath = path.join(projectRoot, "footage_manifest.json");
    await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2));

    res.json({
      ok: true,
      project_root: projectRoot,
      manifest_path: manifestPath,
      file_count: sourceFiles.length,
      important_count: importantFiles.length,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Unknown error";
    res.status(500).json({ error: message });
  }
});

export default router;
