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

### Phase 11: Narrative Analysis + Global Timeline

This phase has three steps: understand the content, select the best takes, and build a multi-track global timeline.

#### Step 1: Narrative Analysis

Use transcripts from all clips to understand what the footage is *about*, not just score it.

**Topic grouping:** Compare transcript content across clips. Identify clips that cover the same topic (e.g., five intro takes all say "hi I'm X, welcome to my channel"). Use transcript similarity (LLM comparison of content, not string matching) to group clips into **topic clusters**.

**Best take selection:** Within each topic cluster, select the best take and deselect the rest with explicit reasons:
- Selected: "take 3 — cleanest delivery, no false starts, complete thought, highest energy"
- Deselected: "take 1 — abruptly stopped at 0:42", "take 2 — 3 false starts in first 10s", "take 4 — audio clipping at 0:15, lower energy", "take 5 — incomplete, trails off"

Selection criteria (in order): completeness of thought → delivery quality (confidence, energy, no stumbling) → audio quality → visual quality.

**Topic boundary detection:** For long clips covering multiple topics, identify where topic shifts occur using transcript content + silence gaps + scene boundaries. Mark these as potential unit split points.

**Narrative order:** Propose a logical story arc across topic clusters: intro → context/problem → explanation → demo → conclusion. This becomes the default `unit_order`.

**Output:** Write `manifest.narrative` with topic clusters, selected/deselected clips with reasons, proposed story order. Deselected clips feed into `discarded_clips` in the edit_manifest (visible but inactive in studio). **Present to user for approval.**

#### Step 2: Build Global Timeline

Build a **multi-track global timeline** from selected clips. This is the universal format that all exporters (FCPXML, Blender, Remotion) read from. See `references/manifest-schema.md` for the full schema.

**Tracks:**
- `main` (video): Primary footage clips in narrative order, with in/out points, crop keyframes
- `overlay` (video): Animations, in-video graphics, PiP overlays positioned by markers
- `sfx` (audio): Sound effects at transition points and emphasis moments
- `music` (audio): Background music with ducking volume curves

**Per-clip data:** Each clip on the timeline is a *reference* to a source clip with its own `in_point`, `out_point`, `trim`, `deleted_ranges`, `speed`, `volume_keyframes`, `transform`, and `crop_9_16` keyframes. A source clip can be referenced multiple times (if split).

**Transitions:** Between clips, with type and duration. Cross Dissolve between units, cuts within units by default.

**Interest scoring and crop keyframes** are assigned per clip segment from vision + transcript + pitch + YOLO data (same analysis as before, but written into the global timeline format).

Write to `manifest.timeline` (multi-track format).

#### Step 3: Decompose into Unit Groups

Units are **logical groupings within the global timeline**, not isolated mini-projects. One unit = one concept/topic.

**Decomposition logic:**
- Each topic cluster from Step 1 becomes a unit
- A single long clip discussing two topics → two units (split at topic boundary)
- Audio-matched clips (camera + screencast with synced audio) → one unit
- Unit contains references to its clips on the global timeline, not copies

**Unit naming**: `unit_{NNN}_{type}_{slug}` — slug from transcript content.

**Unit directory** mirrors main project structure (`raw/`, `audio/`, `frames/`, `analysis/`, etc.) using symlinks. Each unit dir gets its own `footage_manifest.json` + symlinked `style_config.json`.

**Relationship to global timeline:** Units are views into the global timeline. Each unit knows its `timeline_range` (start/end on the global timeline) and its `clip_ids` (which timeline clips belong to it). The global timeline is the source of truth; units provide logical grouping for parallel work.

Present decomposition to user — show unit IDs, types, durations, selected/deselected clips with reasons. **Let them adjust before proceeding.**

Update main manifest: `units[]` array, `pipeline_state.units_decomposed = true`.

### Phase 12: claudepipe studio (INTERACTIVE)

Launch the studio web app for visual unit review and editing:
```bash
cd studio && PROJECT_ROOT=<project_root> npm run dev
```
Tell the user: "Studio running at http://localhost:5173"

**This is the most important phase.** The studio gives the user full visual control over editorial decisions.

#### Studio Capabilities

**Viewing:**
- **Sidebar**: Drag-drop unit reordering, right-click to insert/delete units
- **Elements tab**: Per-unit footage clips with metadata, analysis summary, file drops
- **Player tab**: Frame-accurate video per clip with spatial+temporal markers, transcript subtitles
- **Precision tab**: Zoom view (1x–10x) for precise marker placement
- **Instructions panel**: Per-unit instructions textarea for Claude, marker reference list

**NLE Operations (data mutations on edit_manifest — source files untouched):**
- **Trim**: Set in/out points on a clip via drag handles. Non-destructive — original range preserved, trim range is what the exporter uses
- **Split**: Cut a clip at a point, creating two clip references from one source. Each piece has its own trim range. Transcript segments divide at the split point (time-based, no re-ASR needed)
- **Drag between units**: Move a clip (or split piece) from one unit to another
- **Delete chunk**: Mark a time range within a clip as deleted. Exporter skips these ranges. Deleted chunks are recoverable (remove from `deleted_ranges`)

**Trim enforcement:** The FCPXML exporter hard-clamps all clip references to the trim range. If any timeline reference falls outside the trim, the exporter REJECTS with an error — not silently clips. `deleted_ranges` are similarly enforced. Phase 18 validation catches violations before export. See `references/studio-instruction-protocol.md` for the data model.

**Animation flow checkbox:** Per-unit checkbox "Needs Animation". When checked:
1. The unit's footage is marked as *reference* (not content to render directly)
2. User uploads reference images/sketches via added media, or the footage itself serves as visual reference
3. User writes animation description in instructions textarea
4. Claude enters animation generation mode (Phase 13) for this unit
5. Generated animation becomes the unit's active content

**Teleprompter:** Studio generates a QR code in the header. Scanning opens `http://<local-ip>:5173/teleprompter/<unit_id>` on any local device. Shows the narration script (from Claude-generated content or user-written text in instructions) with configurable auto-scroll speed. Used when user needs to record new voiceover/narration for a unit.

**Versioning (git-based):** Each sync auto-commits `edit_manifest.json` to git. Current version = what's used for building. Previous versions browsable via git history. Restore = checkout specific version of edit_manifest. In studio, current version plays as default; previous versions accessible but clearly marked as history. Per-unit: clear indicator of which clips/version are active for the build.

**Sync**: 30s auto-sync + manual Ctrl+S, writes `edit_manifest.json`. Each sync triggers `git add edit_manifest.json && git commit`.

#### Post-Session Processing

Wait for the session to end (`edit_manifest.json` session.active = false). Then:
1. Read `edit_manifest.json`
2. Apply clip edits (trims, splits, deletes, moves) to the global timeline
3. Apply `unit_order` changes
4. Process per-unit instructions and markers (see `references/studio-instruction-protocol.md`)
5. For units with `pipeline_requested: true` or `needs_animation: true`: spawn agents per Agent Spawn Protocol
6. Show summary of all changes, ask for confirmation
7. Proceed to Phase 13+

### Agent Spawn Protocol

When spawning parallel agents for per-unit work (Phases 13–15), each agent MUST receive the following context. This is not optional — agents without full context produce isolated, inconsistent work.

**Read-only context (every agent gets all of this):**
- `SKILL.md` + `USER-SKILL.md` — full pipeline knowledge and operational findings
- **Global timeline** — all units, all clips, all transcripts, all analysis
- **All unit instructions** — what the user asked for across ALL units, not just this agent's unit
- **All agent assignments** — what every other agent is working on, with their unit IDs and instructions
- **Edit manifest** — markers, trims, splits, discards, added media — for ALL units
- **Style config** — colors, fonts, dimensions, pipeline settings
- `references/studio-instruction-protocol.md` — how to interpret markers and instructions

**Mutation scope (strictly enforced):**
- Agent may ONLY modify its assigned unit's data: clips, timeline segment, markers, SFX, animations within that unit
- Agent may NOT modify: other units, global timeline order, inter-unit transitions, music tracks, global settings

**Inter-unit work stays with the main agent:**
- Transitions between units
- Music ducking across the full timeline
- Narrative order changes
- Global timeline reordering

**Structural fluency:** Each agent must understand the manifest schema, edit_manifest schema, marker semantics, trim/split mechanics, and the universal timeline format as working knowledge — not as "here's some context" but as the vocabulary it uses to make correct mutations.

#### Agent Execution Protocol

Agents MUST NOT take the path of least resistance. When uncertain, FAIL — do not produce garbage and claim success. Every agent follows this execution flow:

**Step 1 — Dry-run plan.** Before doing ANY work, the agent writes a plan stating:
- What it will do (specific actions, not vague descriptions)
- Which tools/APIs it will use (e.g., "Lyria 2 on Vertex AI", NOT "generate music")
- What the expected output looks like (file format, duration, placement)
- What it will NOT do (explicit anti-patterns from SKILL.md and USER-SKILL.md)

The plan is written to `claude_notes[unitId]` so the main agent and user can review it.

**Step 2 — Execute.** Carry out the plan. If something fails or the chosen approach doesn't work, do NOT silently switch to an easier but wrong approach. Instead, update `claude_notes` with the failure and try the next correct alternative from the plan.

**Step 3 — Quality gates.** Run ALL quality gates for the phase (see below). Every gate must pass. Results are written to `claude_notes[unitId]` with pass/fail status per gate.

**Step 4 — Handoff.** Report results to the main agent:
- If ALL gates pass: report success with gate results
- If ANY gate fails: report FAILURE with details of what failed and why. Mark unit `status: "needs_review"`. Do NOT claim success with bad output.

#### Quality Gates by Phase

**Phase 13 — Animations:**
- [ ] `RENDER_VALID`: Animation renders without errors. ffprobe confirms valid video file.
- [ ] `DURATION_MATCH`: Duration within 0.5s of expected. If voiceover exists, animation duration matches voiceover.
- [ ] `RESOLUTION_MATCH`: Resolution matches `style_config.json` (width/height).
- [ ] `STYLE_MATCH`: Colors used are from `style_config.json` palette (sample 3 frames, extract dominant colors, compare).
- [ ] `PLACEMENT_VALID`: Animation has valid `timeline_start`, `unit_id`, and correct track assignment in global timeline.
- [ ] `CONTENT_RELEVANT`: Animation content matches the transcript/instruction context (not generic placeholder graphics).

**Phase 14 — SFX:**
- [ ] `FILE_VALID`: Each SFX file > 10KB. ffprobe confirms valid audio codec, sample rate, duration.
- [ ] `DURATION_MATCH`: Duration within 0.5s of requested.
- [ ] `NOT_SILENCE`: File contains actual audio content (peak amplitude > -40dB). Play first 2 seconds and verify.
- [ ] `PLACEMENT_CONCRETE`: Every SFX has concrete `after_segment` reference (NOT null). `time_offset_seconds` is set.
- [ ] `CONTEXT_MATCH`: SFX type matches its context — transition points → whoosh/riser, text appearance → pop/swoosh, emphasis → blip/hit. NOT random sounds at random times.
- [ ] `TIMELINE_BOUNDS`: All SFX placements fall within the unit's timeline range.

**Phase 15 — Music:**
- [ ] `NOT_SPEECH`: Generated audio is instrumental music, NOT speech narration. Play first 10 seconds — if you hear words or human voice describing music, the gate FAILS. This means you used the wrong API (Gemini TTS instead of Lyria).
- [ ] `FILE_VALID`: ffprobe confirms valid audio. File size > 100KB for 30s WAV. Correct sample rate (48kHz).
- [ ] `NO_DISTORTION`: No clipping artifacts (peak amplitude < 0dBFS).
- [ ] `STYLE_MATCH`: Music style matches user-approved brief (genre, mood, energy level).
- [ ] `DUCKING_COMPUTED`: Ducking keyframes computed from VAD data and written to manifest. Keyframes exist for every speech segment.
- [ ] `API_CORRECT`: Music was generated using Lyria 2 (Vertex AI) or Lyria RealTime (Gemini API), or provided by user. NOT generated using Gemini `response_modalities=["AUDIO"]` — that is TTS and will always fail `NOT_SPEECH`.

#### Failure Protocol

When an agent cannot complete its task correctly:

1. **Do NOT produce garbage.** An empty result is better than a wrong result that downstream phases will treat as correct.
2. **Do NOT silently switch approaches.** If Lyria fails, don't fall back to Gemini TTS. Instead, report the Lyria failure and suggest alternatives.
3. **Write failure details to `claude_notes[unitId]`:** what was attempted, what failed, what the error was, what alternatives exist.
4. **Mark unit status as `"needs_review"`.**
5. **Report failure to main agent** with enough detail that the user can decide what to do (retry with different params, skip music, provide their own track, etc.).

The main agent presents all agent results (successes AND failures) to the user. The user decides how to handle failures — not the agent.

### Phases 13–15: Per-Unit Refinement (PARALLELIZABLE)

These phases run **independently per unit**. Launch parallel agents following the Agent Spawn Protocol above. Each agent works on its assigned unit with full global context but scoped mutations. Every agent MUST pass its phase-specific quality gates before handoff.

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

### Phase 16b: Merge Units into Global Timeline

Read all unit manifests from `units/*/footage_manifest.json`. Collect updated clips, SFX, animations from each unit. Merge into the global multi-track timeline. Rebase file paths from unit-relative to project-relative. Back up pre-merge timeline as `_pre_merge_timeline`. Update `pipeline_state.units_merged = true`.

**Merge rules:**
- Unit-level changes (SFX, animations, clip edits) are applied to the global timeline tracks
- Inter-unit transitions are preserved from the global timeline (main agent controls these)
- Music tracks are global — merge ducking keyframes from all units' VAD data
- Animations from each unit go to the `overlay` track with correct timeline positions

**Merge output contract** (Phase 17 exporters depend on this exact structure):
- Each clip on a track MUST have: `id`, `source_clip_id`, `in_point`, `out_point`, `trim`, `deleted_ranges`
- `timeline.tracks[].clips` MUST be ordered by `timeline_start`
- Transitions MUST reference valid `from_clip`/`to_clip` IDs
- All source clips referenced by timeline clips MUST exist in the main `clips[]` array — including animation clips and inserted media
- Use `ffprobe` to verify actual durations — do not trust unit manifest values blindly
- Trim ranges and deleted_ranges from the edit_manifest MUST be applied — the exporter enforces these but the merge should respect them too

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

### Phase 18: Sync Validation + Trim Enforcement

Verify the assembled project before export. **This is the enforcement layer — it fails the build rather than producing bad output.**

**Media validation:**
- All referenced media files exist on disk
- Audio/video durations match manifest values (ffprobe verification)

**Timeline validation:**
- No clip overlaps within a track
- Transitions reference valid clip pairs
- SFX/overlay placements fall within timeline bounds
- Unit groups don't overlap on the timeline

**Trim enforcement (critical):**
- Every clip reference on the timeline MUST fall within its `trim` range
- No clip reference may include content from `deleted_ranges`
- If ANY violation is found: **REJECT the build with an explicit error** listing every violation. Do NOT silently clamp or adjust — fail loudly so the user can fix the source data
- This prevents Claude or any agent from accidentally (or hallucination-driven) including trimmed/deleted content

Report all issues. Build cannot proceed to Phase 17 export until validation passes.

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
- `studio-instruction-protocol.md` — How Claude interprets markers, instructions, trim/split/drag/delete operations
- `pipeline-runtime-notes.md` — Operational findings: dependency gotchas, Chirp 2 location constraints, manifest format expectations between phases

## Key Rules

1. **Manifest is truth** — all state lives in `footage_manifest.json` (source data + global timeline) and `edit_manifest.json` (user edits)
2. **Never modify originals** — `raw/` contains symlinks or denoised muxed copies (Phase 3 Step 4), originals stay at source_path
3. **Easing is NEVER linear** — always BEZIER, SINE, EXPO, BACK, ELASTIC, BOUNCE, or CONSTANT
4. **Nepali first** — default language is "ne", ASR handles code-switching
5. **User has final say** — at every approval gate, present options and wait
6. **Style consistency** — always read `style_config.json` for colors/fonts/dimensions
7. **Global timeline, scoped units** — one timeline for the whole video. Units are logical groupings within it. Parallel agents read the full context but only write to their assigned unit
8. **Agent spawn protocol** — every parallel agent gets full global context + all agent assignments. Mutations scoped to assigned unit only. No exceptions.
9. **Trim is sacred** — user-set trim ranges and deleted chunks are enforced by the exporter. No agent, no phase, no script can override trims. Phase 18 validation rejects builds that violate trims.
10. **Unit = concept** — one unit represents one topic/concept, not one clip. A clip covering two topics becomes two units. Five takes of the same intro is one unit with the best take selected.
11. **Scripts are optional** — reference implementations in `scripts/` can be used or bypassed; do what's most effective for the phase
