# claudepipe

AI video editing pipeline implemented as a Claude Code skill (`/footage`). Processes raw camera footage + screen recordings into fully edited Blender VSE and FCPXML projects.

## Architecture

**Manifest-driven**: `footage_manifest.json` (source data + global timeline) and `edit_manifest.json` (user edits) are the single source of truth. Every pipeline phase reads/writes these files. All state is here — not in memory, not in scripts, not in variables.

**Global timeline with unit decomposition**: One multi-track timeline for the entire video. Units are logical groupings (one topic = one unit) within that timeline — they are NOT isolated mini-projects. Parallel agents read the full global context but only write to their assigned unit.

**Non-destructive editing**: Source files are never modified. `raw/` contains symlinks (or denoised muxed copies from Phase 3). Trims, splits, deleted ranges are metadata in manifests. Exporters enforce these constraints.

**Two-component system**:
- `.claude/skills/footage/` — The pipeline spec (SKILL.md), 19 reference Python scripts, 13 reference docs, style config
- `studio/` — React + Express web app for visual timeline editing (import mode + studio mode)

## Build & Run

```bash
# Studio web app (two modes)
cd studio && npm run dev                          # Import mode (file browser, project creation)
cd studio && PROJECT_ROOT=/path/to/proj npm run dev  # Studio mode (timeline editor)

# Individual commands
cd studio && npm run dev:server   # Express only (:3001)
cd studio && npm run dev:vite     # Vite frontend (:5173, proxies /api → :3001)
cd studio && npm run build        # Production build
```

Pipeline scripts (all take `<project_root>` as first arg, read/write `footage_manifest.json`):
```bash
python3 scripts/check_deps.py <proj>
python3 scripts/scan_classify.py <proj>
python3 scripts/extract_audio.py <proj>
python3 scripts/run_asr.py <proj>
python3 scripts/run_vad_pitch.py <proj>
python3 scripts/detect_scenes.py <proj>
python3 scripts/extract_frames.py <proj>
python3 scripts/run_yolo.py <proj>
python3 scripts/sync_screen_recording.py <proj>
python3 scripts/build_manifest.py <proj>
python3 scripts/decompose_units.py <proj>
python3 scripts/generate_sfx.py <proj>
python3 scripts/generate_music.py <proj>
python3 scripts/generate_thumbnail.py <proj>
python3 scripts/merge_units.py <proj>
python3 scripts/build_blender_project.py <proj>
python3 scripts/export_fcpxml.py <proj>
python3 scripts/validate_sync.py <proj>
python3 scripts/cleanup.py <proj>
```

## Tech Stack

| Layer | Stack |
|---|---|
| Studio frontend | React 19, TypeScript 5.8, Vite 6, Tailwind 4, Radix UI, dnd-kit, WaveSurfer |
| Studio backend | Express 5, tsx, multer |
| Pipeline scripts | Python 3.10+, ffmpeg/ffprobe |
| Vision | Gemini Flash 2.5 (default), Claude Vision (fallback) |
| ASR | Google Chirp 2 (Nepali+English), ne-NP on us-central1 |
| Audio | DeepFilterNet Rust CLI (`deep-filter`), librosa, Silero VAD, torch ecosystem |
| Detection | YOLO11 (ultralytics), OpenCV |
| Music | Lyria 2 (Vertex AI), Lyria RealTime (Gemini API) |
| SFX | ElevenLabs `text_to_sound_effects` |
| Animations | Manim, Remotion |
| NLE Export | Blender 4.x headless, FCPXML 1.9 |

## Directory Layout

```
.claude/skills/footage/
  SKILL.md              # Pipeline spec — the authoritative document (read this first)
  USER-SKILL.md         # Operational findings, gotchas, workarounds (evolves per run)
  scripts/              # 19 reference Python scripts (optional — not mandatory executables)
  references/           # 13 technical docs (manifest schema, NLE formats, API guides, etc.)
  templates/            # style_config_default.json

studio/
  server/               # Express backend (routes: manifest, edit-manifest, filesystem, media, upload, project)
  src/                  # React frontend (api/, hooks/, types/, lib/, components/)
  package.json          # Dependencies and scripts
  vite.config.ts        # Proxy /api → :3001

# Runtime (gitignored, created per project)
footage_project_*/      # Project root
  raw/                  # Symlinks or denoised muxed copies of source footage
  audio/denoised/       # Extracted + denoised audio
  frames/               # Extracted keyframes
  analysis/             # transcripts/, vad/, pitch/, scenes/, yolo/, vision/
  sfx/ music/ animations/ thumbnails/
  blender/ exports/     # NLE output
  units/                # Per-unit dirs with symlinked structure
  footage_manifest.json
  edit_manifest.json
  style_config.json
```

## Key Conventions

**Scripts are reference implementations, not mandatory.** SKILL.md defines what each phase does — that is the spec. Scripts can be used, modified, or bypassed. Complex phases (Blender assembly, FCPXML, YOLO, VAD) benefit from scripts; simpler ones are often easier inline.

**Manifest keys matter.** Phase 8 reads `clip.frames.extracted[].path` — using a different key silently breaks YOLO. Check `references/manifest-schema.md` and `USER-SKILL.md` phase-specific keys table before writing manifest mutations.

**Easing is NEVER linear.** Always use BEZIER, SINE, EXPO, BACK, ELASTIC, BOUNCE, or CONSTANT for crop/animation keyframes.

**FCPXML timing: frame boundary rule.** ALL time values must be exact multiples of `frameDuration`. For 29.97fps: `N*1001/30000s`. One-frame rounding errors cause DaVinci import failures.

**GoPro timecodes.** Must be stripped before FCPXML export: `ffmpeg -i in.mp4 -map 0:v:0 -map 0:a:0 -c copy -write_tmcd 0 out.mp4`.

**DeepFilterNet: use Rust CLI only.** The `deepfilternet` pip package is broken (pulls numpy 1.x, conflicts with cv2/ultralytics). Use the pre-compiled `deep-filter` binary.

**torch ecosystem.** Always upgrade torch/torchaudio/torchvision/torchcodec together. `silero-vad` can trigger version drift.

**Chirp 2 ASR constraints.** Only on `us-central1`/`europe-west4`/`asia-southeast1`. Single `ne-NP` language code only (multi-language codes require different locations). Sync limit 60s — split longer clips into 52s chunks with 3s overlap.

**DaVinci Resolve ignores** volume keyframes and audio transitions on FCPXML import. This is a known bug, not our code. Write keyframes for FCP compatibility, store in manifest for manual DaVinci application.

## Agent Protocol

When spawning parallel agents for per-unit work (Phases 13-15):
1. **Never rewrite user instructions** — pass verbatim to subagents
2. **Dry-run plan before spawning** — show user what each agent will do, wait for approval
3. **Full global context to every agent** — all units, all instructions, all agent assignments
4. **Mutations scoped to assigned unit only** — use `PATCH http://localhost:3001/api/edit-manifest` with typed operations when studio server is running, fall back to `units/{unit_id}/agent_output.json` when offline
5. **Server is the single writer** — never write to `edit_manifest.json` directly. Check server availability: `curl -s http://localhost:3001/api/status`
6. **Quality gates must pass** — each phase has specific pass conditions (see SKILL.md)
7. **Fail cleanly, never produce garbage** — empty result > wrong result

## What NOT To Do

- Do NOT use `deepfilternet` pip package — use `deep-filter` Rust binary
- Do NOT use Gemini `response_modalities=["AUDIO"]` for music — that is TTS, produces speech
- Do NOT use `auto` language detection with Chirp 2 — misidentifies Nepali as Latin
- Do NOT use linear easing for anything
- Do NOT have parallel agents write to shared manifest files directly — use the HTTP operations API
- Do NOT use `POST /api/edit-manifest` (deprecated) — use `PATCH /api/edit-manifest` with typed operations
- Do NOT silently clamp trims — fail loudly if timeline references violate trim ranges
- Do NOT round FCPXML time values independently — accumulate integer frame counts
- Do NOT assume media paths are recursive in DaVinci — consolidate flat to `exports/media/`
