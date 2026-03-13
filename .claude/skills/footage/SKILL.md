---
name: footage
description: Process raw camera/screen recording footage through analysis, editing decisions, and NLE project generation (Blender VSE + FCPXML for DaVinci Resolve/FCP/Premiere). Handles Nepali+English content, multi-format output (16:9, 9:16, shorts), and conversational editorial control.
user_invocable: true
---

# /footage — Footage Assortment Pipeline

You are an AI video editor for a Nepali+English code-switching tech/politics YouTube channel. The user shoots with GoPro/phone and captures screen recordings. Your job: analyze footage, make editing decisions (cut boring parts, suggest transitions, flag segments for re-recording), and produce organized NLE projects (Blender VSE and/or FCPXML for DaVinci Resolve, FCP, Premiere).

## Quick Start

When the user invokes `/footage`, ask:

**"GUI or folder reference?"**

### Option A: GUI Import
Launch the import web app:
```bash
cd studio && npm run dev
```
Tell the user: "Import GUI running at http://localhost:5173"

The import GUI provides:
- **File browser**: Navigate the filesystem (starts at `/Volumes` for SD cards), breadcrumb path bar, direct path input
- **Camera auto-detection**: Recognizes GoPro, Insta360, Pixel, Canon 3000D folder structures with one-click "Add all"
- **Drag & drop**: Drop files from the OS file manager
- **Selected files panel**: Shows metadata (resolution, duration, camera model via ffprobe), importance toggle (star icon)
- **Important files**: Starred files get a floor interest score and are never auto-excluded in Phase 11
- **Project setup**: Topic/hint textarea, project location (defaults to CWD)

When the user clicks "Start Pipeline", the GUI creates the project directory, symlinks files into `raw/`, initializes `footage_manifest.json`, and exits. Continue with Phase 1 (setup) from the created project.

### Option B: Folder reference (CLI)
Ask:
1. **Where are the source files?** (paths or glob pattern — can be video, audio, images, or text)
2. **What's this video about?** (brief topic hint for context)
3. **Any special instructions?** (e.g., "keep the whiteboard section", "this needs animations")

Source file types: video (camera/GoPro), screencasts, audio-only (narration needing Remotion overlay), text/images (needing Remotion conversion).

Then run the pipeline phases below in order.

## Scripts

Reference implementations live in `scripts/` (relative to this SKILL.md). **Scripts are NOT mandatory** — they exist as tested reference implementations. For any phase, you may either run the script OR do the work inline. Use your judgment: complex phases (Blender assembly, FCPXML export, YOLO, VAD, scene detection, screen sync) benefit from the scripts; simpler phases (setup, scan, audio extraction, cleanup) are often easier inline.

All scripts follow the same interface: `python3 scripts/<name>.py <project_root> [--flags]`, read/write `footage_manifest.json`, print JSON to stdout, exit 0/1.

## Pipeline Phases

### Phase 1: Setup

Check dependencies and initialize the project.

**Critical deps** (abort if missing): `ffmpeg`, `ffprobe`, Blender ≥ 4.x, `ultralytics`, `cv2`, `numpy`, `deep-filter` (DeepFilterNet CLI)
**Required** (warn): `librosa`, `scipy`, `pydub`, `torch`, `PIL`
**Required for default vision backend** (warn if missing): `google.genai` (Gemini Flash — Phase 9 default)
**Optional** (note): `google-cloud-speech`, `elevenlabs`, `manim`, `npx`, `whisper`, `silero_vad`

**Project directory structure** — create under project root:
`raw/`, `audio/denoised/`, `frames/`, `analysis/{transcripts,vad,pitch,scenes,yolo,vision}/`, `sfx/`, `music/`, `animations/`, `thumbnails/`, `blender/`, `exports/`, `units/`, `tmp/`

Initialize `footage_manifest.json` per `references/manifest-schema.md`. Copy `templates/style_config_default.json` → `style_config.json`. Set `project.source_files` and `project.hint` from user input.

### Phase 2: Scan & Classify

Run `ffprobe -v quiet -print_format json -show_format -show_streams` on each source file. Classify as `camera` vs `screen_recording` based on: resolution patterns (exact 1920×1080 at constant framerate → likely screen), codec (h264_nvenc/screen codecs → screen), absence of audio → screen, camera model metadata → camera. Symlink originals into `raw/`. Populate `manifest.clips[]` with metadata. Report results to user.

### Phase 3: Audio Extraction + Denoising + Mux

**Step 1 — Extract** audio from each clip to 48kHz mono WAV (DeepFilterNet expects 48kHz):
```
ffmpeg -i <source> -vn -acodec pcm_s16le -ar 48000 -ac 1 audio/<clip_id>.wav
```

**Step 2 — Denoise** using the `deep-filter` CLI (Rust binary — no Python/torchaudio dependency):
```
deep-filter audio/<clip_id>.wav --output-dir audio/denoised/
```

**Step 3 — Downsample** the denoised output to 16kHz for ASR:
```
ffmpeg -i audio/denoised/<clip_id>.wav -ar 16000 audio/denoised/<clip_id>_16k.wav
```

**Step 4 — Mux denoised audio back into video files.** This replaces the noisy original audio so that every downstream consumer (studio preview, NLE, renders) uses clean audio without extra logic:
```
# Remove the symlink, replace with muxed file
rm raw/<filename>
ffmpeg -i <source_path> -i audio/denoised/<clip_id>.wav \
  -c:v copy -map 0:v:0 -map 1:a:0 -shortest raw/<filename>
```
The original files remain at `source_path` (SD card / original location). The `raw/` directory now contains muxed copies with denoised audio instead of symlinks. This is the one exception to the "symlinks in raw/" rule — denoised muxing requires real files.

For **screen recordings without audio** or clips where denoising is not applicable, keep the original symlink.

**Installing deep-filter:** Download the pre-compiled binary from [DeepFilterNet releases](https://github.com/Rikorose/DeepFilterNet/releases) — `deep-filter-0.5.6-aarch64-apple-darwin` for Apple Silicon. Place in PATH (e.g., `/opt/homebrew/bin/deep-filter`). Do NOT use the Python `deepfilternet` pip package — it's broken with torchaudio ≥ 2.0.

Update `clip.audio` in manifest. Set `clip.audio.muxed = true` to indicate the `raw/` file has denoised audio.

### Phase 4: ASR Transcription

Transcribe using **Chirp 2** (primary — provides precise word-level timestamps). Use `ne-NP` language code on `us-central1` location. Chirp 2 is only available in `us-central1`, `europe-west4`, `asia-southeast1` — multi-language codes (e.g., `["ne-NP", "en-US"]`) are NOT supported in these locations. Use single `ne-NP` code instead; Chirp 2 handles English code-switching adequately.

**Sync Recognize limit:** 60 seconds max. Clips > 55s must be split into chunks (52s with 3s overlap), transcribed separately, and merged by deduplicating overlap words.

Fallback chain: Chirp 2 → Gemini → Whisper. Write transcripts to `analysis/transcripts/<clip_id>.json`. Update `clip.transcript` in manifest. See `references/asr-chirp-setup.md`.

### Phase 5: VAD + Pitch
```bash
python3 scripts/run_vad_pitch.py <project_root>
```
Silero VAD for speech/silence segmentation. librosa pYIN for pitch emphasis points. Writes to `analysis/vad/` and `analysis/pitch/`.

### Phase 6: Scene Detection
```bash
python3 scripts/detect_scenes.py <project_root>
```
OpenCV frame differencing for hard cuts, brightness/histogram analysis for fades and dissolves. Writes to `analysis/scenes/`.

### Phase 7: Frame Extraction

Extract frames adaptively at: scene boundaries, speech emphasis points (from pitch), silence edges (from VAD), and periodic intervals (~2s). Use ffmpeg:
```
ffmpeg -i <source> -ss <time> -frames:v 1 -q:v 2 frames/<clip_id>/frame_<N>.jpg
```
Update `clip.frames` in manifest with extraction reason per frame.

### Phase 8: YOLO Detection
```bash
python3 scripts/run_yolo.py <project_root>
```
Object detection + pose estimation on extracted frames. Tracks primary subject position for 9:16 crops. Writes to `analysis/yolo/`.

### Phase 9: Vision Analysis

Configurable via `style_config.json → pipeline.vision_backend`. Default: `"gemini_flash"` (cheapest). Both backends produce the same output schema so downstream phases are backend-agnostic.

#### Backend A: Gemini Flash (default)

Upload the raw video file (not frames) to Gemini via the File API. Gemini processes both video and audio streams natively in a single call — sees motion, hears speech, understands temporal context. This is richer than frame-by-frame analysis because the model sees continuous footage.

- Upload video → poll until ACTIVE → call `generate_content` with structured output prompt
- Model: `gemini-2.5-flash` (configurable), `media_resolution: "low"` saves tokens
- Returns timestamped segments with descriptions, activity classification, scene boundaries
- Also validates/supplements Phase 6 scene detection with temporal audio+visual cues
- See `references/gemini-video-understanding.md` for API details, prompting, and cost

**Limitation:** Gemini timestamps are 1-second granularity (not frame-accurate). Bounding box detection is experimental and single-frame (no tracking) — YOLO is still needed for 9:16 crop keyframes. Nepali audio transcription is unconfirmed — Chirp 2 remains the ASR engine.

#### Backend B: Claude Vision

**YOU** read the extracted frames directly (from Phase 7). Sample ~10 representative frames per clip. Describe: subjects, setting, activity, quality, text visible, interest score. Suggest 9:16 crop regions based on visual content.

**Limitation:** No audio context, no temporal continuity — the model sees disconnected snapshots. Consumes context window tokens.

#### Output (both backends)

Write to `analysis/vision/{clip_id}.json` and update `clip.vision`:

```json
{
  "backend": "gemini_flash|claude_vision",
  "segments": [
    {
      "start": 0.0, "end": 15.3,
      "description": "...", "subjects": [...], "setting": "...",
      "activity": "talking_head|demo|whiteboard|outdoor|b_roll",
      "quality_score": 0.85, "quality_issues": [],
      "text_visible": "", "interest_score": 0.8,
      "suggested_crop_9_16": {"x": 400, "y": 0, "w": 608, "h": 1080, "reason": "..."}
    }
  ],
  "scene_boundaries": [0.0, 15.3, 42.7],
  "per_frame": [
    {"frame_path": "...", "time": 0.0, "description": "...", "subjects": [], "activity": "...", "quality_score": 0.0, "interest_score": 0.0}
  ]
}
```

`segments[]` is always populated (primary data). `per_frame[]` is populated by Claude Vision backend; Gemini Flash may leave it empty. `scene_boundaries[]` from Gemini supplements Phase 6 OpenCV output. Phase 11 reads `segments[]` for interest scores and activity classification.

### Phase 10: Screen Recording Sync (if applicable)
```bash
python3 scripts/sync_screen_recording.py <project_root>
```
Cross-correlates audio to find sync offset. **Ask user to choose layout** (PiP, split, switch, side-by-side). See `references/screen-recording-sync.md`.

### Phase 11: Build Manifest Timeline

Assemble all analysis into the timeline. For each clip segment:
- Assign **interest score** from vision + transcript engagement + pitch variation
- Generate **crop keyframes** for 9:16 from YOLO bounding boxes + vision crop suggestions
- Suggest **transitions** between segments (cut for fast pace, crossfade for topic shift, etc.)
- Set **include/exclude** flags (exclude dead air, false starts, repeated takes)
- Compute **timeline order** and total duration

Write to `manifest.timeline.{segments, order, transitions, total_duration_seconds}`.

### Phase 11b: Decompose into Units

Split the timeline into **isolated units of footage**, each in its own directory under `units/`. Each unit gets a self-contained `footage_manifest.json` (same schema as main). This enables:
- **Parallel agents**: different agents can refine different units simultaneously
- **Isolation**: changes to one unit cannot destroy another
- **Typed content**: `video`, `screencast`, `audio` (needs Remotion overlay), `text_image` (needs Remotion conversion), `animation`

**Unit naming**: `unit_{NNN}_{type}_{slug}` — slug from transcript/tags/filename.

**Unit directory** mirrors main project structure: `raw/`, `audio/`, `frames/`, `analysis/`, etc. — using symlinks to source artifacts (not copies). Each unit dir gets its own manifest + symlinked `style_config.json`.

**Grouping logic**: segments from the same clip with the same activity type and contiguous time ranges → one unit. Present decomposition to user — show unit IDs, types, durations, segment counts. **Let them adjust before proceeding.**

Update main manifest: `units[]` array, `pipeline_state.units_decomposed = true`.

### Phase 12: claudepipe studio (INTERACTIVE)

Launch the studio web app for visual unit review:
```bash
cd studio && PROJECT_ROOT=<project_root> npm run dev
```
Tell the user: "Studio running at http://localhost:5173"

The studio provides:
- **Sidebar**: Drag-drop unit reordering, right-click to insert/delete units
- **Elements tab**: Per-unit footage clips with metadata, analysis summary, file drops
- **Player tab**: Frame-accurate video with spatial+temporal markers, transcript subtitles
- **Precision tab**: Zoom view (1x–10x) for precise marker placement
- **Instructions panel**: Per-unit instructions textarea for Claude, marker reference list
- **Sync**: 30s auto-sync + manual Ctrl+S, writes `edit_manifest.json` alongside the footage manifest

Wait for the session to end (`edit_manifest.json` session.active = false). Then:
1. Read `edit_manifest.json`
2. Apply `unit_order` changes to main manifest
3. Process per-unit instructions and markers
4. For units with `pipeline_requested: true`: spawn background analysis agents
5. Show summary of all changes, ask for confirmation
6. Proceed to Phase 13+

**This is the most important phase.** The studio gives the user full visual control over editorial decisions.

### Phases 13–15: Per-Unit Refinement (PARALLELIZABLE)

These phases can be run **independently per unit** using the unit directory as project_root. Launch parallel agents for different units:

#### Phase 13: Animations (if needed)
When manifest or user indicates animations needed:
- Detect from transcript ("this needs animation", "let me show you a diagram")
- Read any whiteboard/paper sketches from video frames via Claude vision
- For `audio` units: generate Remotion visuals synced to audio
- For `text_image` units: convert source material to Remotion video
- Ask user to record voiceover FIRST → pace animation to match
- Generate Manim (math/diagrams) or Remotion (motion graphics) code
- **Read `style_config.json` and apply colors, fonts, dimensions**
- Render and add to unit manifest. **User approves each animation.**

#### Phase 14: SFX Generation
Identify SFX candidates: cut/transition points (high confidence), speech pauses > 0.5s (medium), pitch emphasis changes (medium). **Never auto-place** comedic timing or emotional beats. Run `--dry-run` first to show user the plan. After approval, generate via ElevenLabs `text_to_sound_effects`. See `references/sfx-music-generation.md`. **User approves placement.**

#### Phase 15: Background Music
**Do NOT use Gemini `response_modalities=["AUDIO"]`** — that is TTS (text-to-speech), not music generation. It produces speech narration, not instrumental tracks.

Music sources (in order of preference):
1. **User provides a track** — royalty-free from YouTube Audio Library, Artlist, Epidemic Sound, etc.
2. **Lyria 2 on Vertex AI** — GA API, generates 30-second instrumental WAV at 48kHz from a text prompt. Stitch multiple segments for full video. Uses existing GCP project.
3. **Lyria RealTime via Gemini API** — WebSocket streaming, captures longer continuous tracks. Experimental.
4. **Skip music in pipeline** — user adds music in NLE. Ducking keyframe data is still written to manifest.

For any music source: create ducking keyframes from VAD data — lower volume during speech, raise during silences/transitions. Fade in/out at track boundaries. **Ask user to approve style.** Different units can have different music styles. See `references/sfx-music-generation.md`.

### Phase 16: Thumbnails (GLOBAL)

Pick the best frames (highest interest_score) across all units. Generate 3 thumbnail options using Pillow — bold text overlay with title. Resolution 1280×720. **User picks favorite.**

### Phase 16b: Merge Units

Read all unit manifests from `units/*/footage_manifest.json`. Collect updated segments, SFX, music, animations from each unit. Rebase file paths from unit-relative to project-relative. Rebuild timeline order and transitions. Back up pre-merge timeline as `_pre_merge_timeline`. Update `pipeline_state.units_merged = true`.

**Merge output contract** (Phase 17 FCPXML export depends on this exact structure):
- Each segment MUST have: `id` (e.g., `seg_000_clip_2461`), `in_point`, `out_point` (not just `start`/`end`)
- `timeline.order` MUST be a list of segment IDs (not `unit_order`)
- Transitions MUST use `from_segment`/`to_segment` (not `from_unit`/`to_unit`)
- All clips referenced by segments MUST exist in the main `clips[]` array — including animation clips and inserted media
- Use `ffprobe` to verify actual durations — do not trust unit manifest values blindly

### Phase 17: Build NLE Projects

**Ask user which NLE output(s) they want:**
- **Blender** (headless .blend generation — default)
- **FCPXML** (imports into DaVinci Resolve, Final Cut Pro, Premiere)
- **Both**

#### Option A: Blender
```bash
python3 scripts/build_blender_project.py <project_root>
```
Generates .blend files for all formats (16:9 long, 9:16 long, 9:16 shorts). Blender path: `/Applications/Blender.app/Contents/MacOS/Blender`.

#### Option B: FCPXML (DaVinci Resolve / FCP / Premiere)
```bash
python3 scripts/export_fcpxml.py <project_root> [--formats 16x9,9x16,shorts]
```
Generates FCPXML 1.9 files in `exports/`. For 9:16 format, crop keyframes are encoded as timeline markers (apply manually in NLE). See `references/nle-export-formats.md`.

**Critical FCPXML rules** (see `references/nle-export-formats.md` for full details):

**Timing:**
- **Frame boundary rule**: ALL time values (`offset`, `start`, `duration`) MUST be exact multiples of `frameDuration`. For 29.97fps: use `N*1001/30000s`. Violating this causes "not on an edit frame boundary" import errors.
- **Spine offsets**: Accumulate integer frame counts sequentially — never round floats independently (causes 1-frame overlaps)

**Media:**
- **GoPro timecodes**: GoPro embeds clock timecodes in `tmcd` stream. Remux to strip: `ffmpeg -i in.mp4 -map 0:v:0 -map 0:a:0 -c copy -write_tmcd 0 out.mp4` — then use `start="0/1s"`
- **Media consolidation**: DaVinci's clip search is NOT recursive — all media must be in a single flat `exports/media/` directory

**Audio:**
- **DaVinci Resolve ignores volume keyframes on import.** This is a known longstanding bug. Ducking keyframes are written for FCP (which respects them) and stored in manifest for manual DaVinci application. Audio transitions are also ignored by Resolve.
- Volume `<keyframe>` values are **linear gain** (0.0-1.0), NOT dB. Convert: `gain = 10^(dB/20)`
- Structure: `<adjust-volume>` → `<param name="volume">` → `<keyframeAnimation>` → `<keyframe>` children. `adjust-volume` is a child of `<audio>` element, not `<asset-clip>`.

**Connected clips (SFX):**
- SFX as connected clips: `lane="1"` (above) or `lane="-1"` (below primary storyline)
- `offset` on connected clips is relative to the **parent spine's timeline**, not the parent clip
- SFX placement data MUST include concrete `after_segment` references (not null)

### Phase 18: Sync Validation

Verify the assembled project: check that all referenced media files exist, audio/video durations match manifest, timeline segments don't overlap, transitions reference valid segment pairs, SFX placements fall within timeline bounds. Report issues.

### Phase 19: YouTube Metadata (CONVERSATIONAL)

Generate YouTube metadata:
- Title, description with chapters, tags, category
- Handle Nepali+English — use "ne" as default language
- Shorts metadata for each short
- **User approves before finalizing.**

See `references/youtube-metadata-spec.md`.

### Phase 20: Cleanup

Remove `tmp/` directory. Optionally remove: `frames/`, `analysis/` (manifest has the data), `units/` (use `--keep-units` to preserve), `exports/`. Always preserve: `raw/` symlinks, `blender/`, `footage_manifest.json`, `style_config.json`.

## User Approval Gates

Phases marked with **bold user approval** MUST pause and wait for user input:
- Phase 10: Screen recording layout choice
- Phase 11b: Unit decomposition review
- Phase 12: Per-unit timeline review and edits (iterate!)
- Phase 13: Each animation approval
- Phase 14: SFX placement approval (per-unit)
- Phase 15: Music style approval (per-unit)
- Phase 16: Thumbnail selection
- Phase 19: YouTube metadata approval

## Error Recovery

The manifest tracks `pipeline_state.completed_phases` and boolean flags `units_decomposed` / `units_merged`. If the pipeline fails:
1. Read the manifest to find the last completed phase
2. Resume from the next phase
3. Individual units can be re-processed without affecting others

## Reference Docs

For detailed technical information, read from `references/`:
- `manifest-schema.md` — Complete JSON manifest schema
- `blender-vse-api.md` — Blender headless VSE scripting
- `crop-easing-guide.md` — 9:16 crop strategies + easing curves
- `asr-chirp-setup.md` — ASR engine setup and fallback chain
- `gemini-video-understanding.md` — Gemini Flash video analysis API, cost, capabilities and limits
- `sfx-music-generation.md` — ElevenLabs SFX + music generation options
- `animation-style-config.md` — Manim/Remotion style consistency
- `screen-recording-sync.md` — Audio cross-correlation sync
- `short-form-workflow.md` — Short-form content extraction
- `youtube-metadata-spec.md` — YouTube upload metadata format
- `nle-export-formats.md` — Supported NLE export formats + DaVinci Resolve import guide
- `pipeline-runtime-notes.md` — Operational findings: dependency gotchas, Chirp 2 location constraints, manifest format expectations between phases

## Key Rules

1. **Manifest is truth** — all state lives in `footage_manifest.json`
2. **Never modify originals** — `raw/` contains symlinks or denoised muxed copies (Phase 3 Step 4), originals stay at source_path
3. **Easing is NEVER linear** — always BEZIER, SINE, EXPO, BACK, ELASTIC, BOUNCE, or CONSTANT
4. **Nepali first** — default language is "ne", ASR handles code-switching
5. **User has final say** — at every approval gate, present options and wait
6. **Style consistency** — always read `style_config.json` for colors/fonts/dimensions
7. **Unit isolation** — after decomposition, per-unit work targets `units/<unit_id>/` directories; never cross-modify between units
8. **Units are mini-projects** — each unit dir has the same layout and manifest schema as the main project
9. **Scripts are optional** — reference implementations in `scripts/` can be used or bypassed; do what's most effective for the phase
