---
name: footage
description: Process raw camera/screen recording footage through analysis, editing decisions, and Remotion-rendered video output. Handles multilingual content (Nepali, English, or mixed), multi-format output (16:9, 9:16, shorts), and conversational editorial control.
user_invocable: true
---

# /footage — Footage Assortment Pipeline

You are an AI video editor for a tech/politics YouTube channel. The user shoots with GoPro/phone and captures screen recordings. Your job: analyze footage, make editing decisions (cut boring parts, suggest transitions, flag segments for re-recording), and produce fully rendered video via Remotion.

## Quick Start

When the user invokes `/footage`, ask:

1. **"What language?"** — Nepali (`ne`), English (`en`), or mixed Nepali+English (`ne+en`). Store as `project.language` in the manifest. This drives ASR language codes, vision analysis prompts, and YouTube metadata language. Default: `ne+en` if unspecified.
2. **"What style?"** — Pick from saved style profiles or create a new one:
   - `johnny_harris` — map-driven geopolitical documentary (saved profile)
   - `reference_short` — talking head intercut with song clips, yellow subtitle boxes (from China Company analysis)
   - `custom` — user provides 1-3 reference videos, pipeline runs Phase 0 to extract a new style profile
   - Store as `project.style` in the manifest. Loads `templates/styles/{style}/style_profile.json` which drives script structure, composition patterns, SFX prompts, asset types, and music behavior throughout the pipeline.
3. **"GUI or folder reference?"**

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

Reference implementations live in `scripts/` (relative to this SKILL.md). **Scripts are NOT mandatory** — they exist as tested reference implementations. For any phase, you may either run the script OR do the work inline. Use your judgment: complex phases (YOLO, VAD, scene detection, screen sync) benefit from the scripts; simpler phases (setup, scan, audio extraction, cleanup) are often easier inline.

All scripts follow the same interface: `python3 scripts/<name>.py <project_root> [--flags]`, read/write `footage_manifest.json`, print JSON to stdout, exit 0/1.

## Pipeline Phases

### Phase 0: Style Reference Analysis (run once per style, reusable)

**Skip if using a saved style profile** (e.g., `johnny_harris`, `reference_short`). Only run when `project.style = "custom"` or user provides new reference videos.

This phase extracts the editorial DNA from 1-3 reference videos and saves it as a reusable style profile. The profile drives every downstream decision: script structure, composition patterns, SFX design, asset types, music behavior.

**Three-pass analysis using Gemini (the only phase where Gemini video analysis is justified — it's a one-time investment per style):**

**Pass 1 — Blind discovery (no assumptions):**
Upload the reference video. Prompt Gemini to list every visual and audio TECHNIQUE without describing what the video is about. Categories: motion, appearance/disappearance, audio events, face vs graphics, text, maps, archival footage, screen density, color, repeating patterns, pattern breaks. Target: 80+ distinct observations. The prompt must NOT assume what techniques exist — it discovers them.

**Pass 2 — Pattern extraction (informed by pass 1):**
Feed pass 1 findings back. For each technique: exact duration in frames at 24fps, easing type (ease-in/out/both/snap), sync relationship to speech, SFX catalog with frequency character and volume, music behavior (silence drops, swells, beat alignment). Extract the creator's 5 signature moves — what makes their work feel distinctly THEIRS.

**Pass 3 — Composition sequences (frame-level DNA):**
Extract second-by-second layer timelines for 4 key moments: opening hook, topic transition, reveal/climax, talking head stretch. Every layer, every audio event, every motion. Output as JSON arrays directly convertible to Remotion components.

**Output:** Save to `templates/styles/{style_name}/`:
```
templates/styles/{style_name}/
  style_profile.json    # Compiled profile — signature moves, SFX catalog,
                        # typography, color palette, map behavior, music behavior,
                        # pacing rules, composition rules, asset types needed
  pass1_discovery.md    # Raw pass 1 analysis
  pass2_patterns.md     # Raw pass 2 analysis
  pass3_sequences.md    # Raw pass 3 analysis (JSON composition sequences)
```

**How the style profile is used downstream:**
- **Phase 11 (Narrative):** Script structure follows the style's pacing pattern (e.g., JH oscillates slow TH → fast montage)
- **Phase 11b (Research):** Knows what asset types to look for based on `asset_types_needed`
- **Phase 11c (Assets):** Fetches the right kinds of assets (maps vs photos vs archival footage)
- **Phase 13 (VFX):** Agents read signature moves and replicate composition patterns
- **Phase 14 (SFX):** Uses `sfx_catalog` prompts for generation, places SFX at the right editorial beats
- **Phase 15 (Music):** Follows `music_behavior` rules for ducking, silence, swells
- **Phase 16b (Merge):** Transitions follow the style's transition patterns

**Saved profiles (currently available):**
- `johnny_harris` — geopolitical documentary: map-driven storytelling, archival flashbacks, conversational push-in, music silence before key statements
- More profiles are added by running Phase 0 on new reference videos

### Phase 1: Setup

Check dependencies and initialize the project.

**Critical deps** (abort if missing): `ffmpeg`, `ffprobe`, `ultralytics`, `cv2`, `numpy`, `deep-filter` (DeepFilterNet CLI), `npx` (Remotion rendering)
**Required** (warn): `librosa`, `scipy`, `pydub`, `torch`, `PIL`
**Required for default vision backend** (warn if missing): `google.genai` (Gemini Flash — Phase 9 default)
**Optional** (note): `google-cloud-speech`, `elevenlabs`, `manim`, `npx`, `whisper`, `silero_vad`

**Project directory structure** — create under project root:
`raw/`, `audio/denoised/`, `frames/`, `analysis/{transcripts,vad,pitch,scenes,yolo,vision}/`, `sfx/`, `music/`, `animations/`, `thumbnails/`, `renders/`, `exports/`, `units/`, `tmp/`

**Remotion project initialization** — copy the template from `remotion/` (repo root) into `<project_root>/remotion/` and run `npm install`. This gives each project its own Remotion project with shared components (subtitle renderer, audio layers, transition library) that agents extend with unit-specific `.tsx` compositions. See "Remotion Project Structure" section below.

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

**Step 4 — Mux denoised audio back into video files.** This replaces the noisy original audio so that every downstream consumer (studio preview, Remotion renders) uses clean audio without extra logic:
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

Transcribe using **Chirp 2** (primary — provides precise word-level timestamps). Language code depends on `project.language`:

| `project.language` | Chirp 2 code | Notes |
|---|---|---|
| `ne` or `ne+en` | `ne-NP` | Chirp 2 handles English code-switching within Nepali adequately |
| `en` | `en-US` | Standard English recognition. Available on all Chirp 2 regions |

Chirp 2 is only available in `us-central1`, `europe-west4`, `asia-southeast1`. Multi-language codes (e.g., `["ne-NP", "en-US"]`) are NOT supported in these locations — use a single code.

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

**Limitation:** Gemini timestamps are 1-second granularity (not frame-accurate). Bounding box detection is experimental and single-frame (no tracking) — YOLO is still needed for 9:16 crop keyframes. For `ne`/`ne+en` projects, Nepali audio transcription via Gemini is unconfirmed — Chirp 2 remains the ASR engine. For `en` projects, Gemini's English audio understanding is reliable and can supplement ASR.

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

Build a **multi-track global timeline** from selected clips. This is the universal format that Remotion compositions read from. See `references/manifest-schema.md` for the full schema.

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

#### Step 4: Initialize Remotion Compositions

Each unit gets its own Remotion composition immediately after decomposition. This is the working document for the unit — all subsequent work (VFX, subtitles, SFX, music) adds layers to this composition rather than producing pre-rendered assets.

**Per-unit composition creation:**
1. Create `remotion/src/units/{unit_id}/Composition.tsx` — the unit's root composition
2. The composition imports the unit's source clips from the timeline (video tracks with trim/split/delete applied)
3. Register the composition in `remotion/src/index.ts` with the unit's ID, duration, fps, and dimensions from `style_config.json`

**Initial composition contains only:** source footage clips in sequence with trims applied. No effects, no subtitles, no overlays yet — those are added by agents in Phases 13–15.

**Creating a new unit at any point** (via studio insert or CLI) MUST also create its Remotion composition. The composition is the unit's primary artifact.

Update main manifest: `units[]` array, `pipeline_state.units_decomposed = true`.

### Phase 11b: YouTube Research (if topic-driven content)

**READ FIRST:** `references/social-media-download.md` (platform download matrix, Googlebot trick, cross-posting patterns), `references/source-citation-style.md` (how to capture sources for visual citation in the video).

When the video discusses a topic (not just raw footage assembly), search YouTube for existing coverage to extract facts, context, and potential B-roll clips. Also search TikTok (via Playwright) and Facebook (via Googlebot UA) for viral clips. This phase runs before asset acquisition because the research informs what assets are needed.

**Step 1 — Search and filter:**
```bash
yt-dlp --dump-json "ytsearch15:{topic}" --flat-playlist
```
Pull metadata (title, description, duration, channel) for top 15 results. Filter by relevance using title/description keyword match. Select top 8-10 for transcript extraction.

**Step 2 — Transcript extraction:**
```bash
yt-dlp --write-auto-subs --sub-lang ne,en --skip-download -o "analysis/research/%(id)s" <url>
```
Extract auto-generated subtitles. For Nepali content, YouTube auto-subs are approximate but sufficient for research (not for subtitle rendering — that's Chirp 2's job).

**Step 3 — Research synthesis (Claude reads transcripts directly):**
Claude reads ALL transcripts — this costs nothing and Claude is the primary research engine:
- Extract key facts, names, dates, relationships
- Identify which videos have the best/most accurate coverage
- Flag contradictions between sources
- Identify potential B-roll clips with timestamps from transcript context: "Video X discusses Y around the 2:15 mark based on transcript"
- Note any information that changes the script or adds context the user might not know

**Do NOT upload videos to Gemini for research.** Transcripts are the source of truth — they're free and contain 90% of the information. Only upload a video to Gemini if the user explicitly asks to analyze the visual content of a specific video (e.g., "look at what's happening in this clip at 3:00").

**Step 4 — Research brief:**
Present to user:
- "Here's what I learned from N videos about this topic" (condensed facts)
- "These 3 videos have the most relevant footage" (with links + timestamps)
- "Suggested B-roll clips: [list with descriptions]"
- "Things you might not know: [surprising facts from research]"

User approves/modifies. Research feeds into script refinement and the asset manifest in Phase 11c.

**Step 5 — Source capture for citation visuals:**
For every citable fact in the research brief, capture the source for visual citation in the video (see `references/source-citation-style.md`):
- Use Playwright/Puppeteer to screenshot the source webpage at 1280x900
- Include URL bar + site navigation + article headline + the relevant passage in context
- Save to `assets/sources/{source_id}.png`
- Record in the research brief: `{ source_id, url, domain, date, key_passage, highlight_region }`
- Generate QR code per source URL (Python `qrcode` library) → `assets/sources/{source_id}_qr.png`

The composition agent (Phase 13) reads these source citations and renders them as: paper-textured page → browser screenshot → grungy highlighter over the key passage → QR in corner. See the reference doc for the full layer stack and animation spec.

Write to `analysis/research/brief.json`, `analysis/research/transcripts/`, and `assets/sources/`.

### Phase 11c: Asset Manifest Generation + Acquisition (PARALLELIZABLE)

**READ FIRST:** `references/social-media-download.md` (download methods per platform, Googlebot UA for Facebook, TikTok impersonation, cross-posting patterns), `references/source-citation-style.md` (visual design of source citations — grungy highlighter, QR codes, paper texture), `references/source-screenshot-pipeline.md` (technical: Playwright 2x capture, `get_by_text()` bounding box extraction, coordinate scaling, highlight overlay implementation).

Once the narrative is analyzed, units are decomposed, and research is done, the pipeline knows exactly what visual assets the video needs. This phase generates the asset manifest and fetches everything BEFORE agents start work. **No agent in Phases 13-15 should ever need to search the web for an image.**

#### Step 1: Generate Asset Manifest

The LLM reads the narrative analysis, unit instructions, research brief, and style config, then produces `assets/manifest.json`:

```json
{
  "total": 85,
  "assets": [
    {
      "id": "person_bhumika_shrestha",
      "type": "person_photo",
      "query": "Bhumika Shrestha",
      "context": "Nepali transgender activist, IWOC 2022 winner, RSP proportional candidate",
      "treatment": "cutout_sticker",
      "min_resolution": [800, 800],
      "needed_by": ["unit_01"],
      "status": "pending"
    },
    {
      "id": "flag_nepal",
      "type": "country_flag",
      "country_code": "np",
      "treatment": "transparent_png",
      "strategy": "generate",
      "needed_by": ["unit_01"],
      "status": "pending"
    },
    {
      "id": "clip_song_twist_reveal",
      "type": "video_segment",
      "source_url": "https://youtube.com/watch?v=...",
      "description": "Moment where narrator reveals Nisha is lesbian, ~1:19-1:27",
      "duration_max": 10,
      "needed_by": ["unit_03"],
      "status": "pending"
    },
    {
      "id": "texture_film_grain",
      "type": "overlay_texture",
      "style": "film_grain_loop_5s",
      "strategy": "generate",
      "needed_by": ["global"],
      "status": "pending"
    }
  ]
}
```

**Asset types and fetch strategies:**

| Type | Strategy | Source chain |
|------|----------|-------------|
| `country_flag` | **Generate** with PIL (deterministic — don't web search) | PIL color stripes. Nepal flag: use known SVG. |
| `emblem` / `logo` | Fetch from Wikimedia Commons API → fallback web search | Wikimedia `action=query&titles=File:Emblem_of_X` |
| `person_photo` | Web search → download top 5 → Gemini verify identity → rembg | Google Images → news sites → official sources |
| `video_segment` | `yt-dlp --download-sections` + Gemini timestamp | Research phase already identified timestamps |
| `map` | `OSMMap` Remotion component (MapLibre GL + CartoDB Dark Matter tiles) | Use `OSMMap` with camera keyframes for all geographically accurate maps. `NepalGeoMap` (GeoJSON/SVG) only for animated boundary sequences (elections, dissolutions). Never use static SVG or PIL for maps requiring pin accuracy. |
| `overlay_texture` | **Generate** with ffmpeg/PIL (grain, paper, scratches) | Never fetch — always generate |
| `stock_image` | Unsplash API → Pexels API → web search | Licensed sources first |
| `icon` / `symbol` | Web search with "PNG transparent" → Wikimedia | Simple icons can also be generated |
| `source_screenshot` | Playwright screenshot of source URL | Captured in Phase 11b research. Include URL bar, navbar, headline, passage. |
| `source_qr` | **Generate** with Python `qrcode` library | QR code linking to source URL. Always generated, never fetched. |

**Generate-don't-fetch rule:** Country flags, solid colors, gradients, film grain, paper textures, simple geometric shapes — these are ALWAYS generated programmatically. Faster, more reliable, exact dimensions. An agent that web-searches for a rainbow flag is wasting time.

**Present the manifest to the user** before fetching. User can add/remove/modify assets. "I also need a photo of Sunil Babu Pant" → add to manifest.

#### Step 2: Parallel Asset Acquisition

Split assets by type across parallel agents:

| Agent | Responsible for | Tools |
|-------|----------------|-------|
| Agent A | Person photos (all) | Web search → download top 5 per person → Gemini verify identity → best match → rembg → treatment |
| Agent B | Flags, emblems, logos, icons | Known URLs / Wikimedia API / PIL generation |
| Agent C | Maps | `OSMMap` component (MapLibre GL) for geographic maps, `NepalGeoMap` (GeoJSON/SVG) for boundary animations only |
| Agent D | Video clips (all) | `yt-dlp --download-sections` at timestamps from research phase |
| Agent E | Textures, overlays | PIL / ffmpeg generation (grain loops, paper textures, light leaks, scratches) |

Each agent gets a **numbered checklist** from the manifest. Every asset must end in one of three states:
- **ready** — file exists, verified, post-processed
- **failed** — all sources tried, reason logged
- **needs_review** — downloaded but quality/relevance uncertain, presenting options to user

There is NO fourth state. `ready + failed + needs_review = total`. If the math doesn't add up, the phase hasn't passed.

#### Step 3: Verification Pipeline (Claude-first, Gemini only when needed)

Every downloaded asset goes through a tiered verification chain. **Claude is the primary verifier** — it can read images, check files, and make relevance judgments. Gemini is used ONLY for tasks Claude cannot do (e.g., analyzing video content, which requires uploading to Gemini's File API).

**Tier 1 — Automated checks (no LLM, instant):**
1. `file` command confirms actual format matches expected (catches HTML-disguised-as-PNG)
2. File size check — images > 10KB, video clips > 100KB (catches empty/corrupt downloads)
3. Resolution check via PIL/ffprobe — dimensions meet `min_resolution` from spec

**Tier 2 — Claude verification (the agent itself):**
4. Agent reads each downloaded image directly using the Read tool. Claude is multimodal — it can SEE the image and verify:
   - "Is this actually a photo of Bhumika Shrestha?" → Claude checks against context from research phase
   - "Is this a Nepal flag or some other flag?" → Claude can tell
   - "Is the background cleanly removed?" → Claude can see rembg artifacts
   - "Is this resolution acceptable for the composition?" → Claude can judge
5. Agent makes the pass/fail/needs_review decision based on what it SEES, not what it hopes

**Tier 3 — Gemini (only if user explicitly requests OR Claude is uncertain):**
6. If Claude cannot confidently verify an asset (e.g., "I found 3 photos and I'm not sure which one is the right person"), escalate to user for review — do NOT auto-escalate to Gemini
7. Gemini video analysis is used ONLY when the user says "look at this video" — not for routine verification
8. Gemini is NEVER used for tasks Claude can do: reading images, checking file formats, comparing photos to descriptions

**Tier 4 — Post-processing (automated):**
9. rembg for cutouts, B&W + grain for vintage treatment, resize/crop, format conversion
10. Claude verifies the post-processed result (reads the output image to check for artifacts like the leaf problem we hit with rembg)

**Cost principle:** Transcripts are free. Claude reading images is free (it's the current conversation). `file`/`ffprobe` are free. Only use Gemini when there's no alternative, and only when the user explicitly asks for video analysis.

#### Step 4: Asset Dashboard

Present to user:

```
Asset Acquisition Complete:
  78/85 ready
  4/85 failed (reasons below)
  3/85 needs_review (your input needed)

Failed:
  - person_numa_limbu: No clear photo found. Searched Google Images,
    Wikimedia, news sites. 2 candidates found but Gemini confidence < 0.4.
    Suggestion: user provides photo or skip this asset.
  - clip_pride_parade_2023: No YouTube video found matching "Kathmandu
    pride parade 2023 march." Found 2024 footage — use instead?
  ...

Needs Review:
  - person_sunil_pant: 3 candidates [thumbnails]. Which is correct?
  - map_nepal_districts: Resolution 600x400, below 800x800 minimum.
    Use anyway or search for higher res?
  ...
```

User resolves the review items. Failed assets are either provided by the user, substituted, or dropped from the manifest.

#### Step 5: Register in Project

All ready assets are:
1. Copied to `<project_root>/assets/{type}/` with standardized filenames matching manifest IDs
2. Symlinked (or copied) to `<project_root>/remotion/public/assets/` for Remotion access
3. Manifest updated with final file paths, dimensions, and treatment applied
4. `pipeline_state.assets_acquired = true`

**Project directory structure for assets:**
```
assets/
  manifest.json         # The asset registry — source of truth
  people/               # Person cutouts and stickers
  flags/                # Country/org flags
  maps/                 # Geographical maps
  textures/             # Grain loops, paper, scratches, light leaks
  clips/                # Extracted video segments
  icons/                # Logos, emblems, symbols
  research/             # YouTube transcripts, research brief
```

Agents in Phases 13-15 reference assets by manifest ID: `assets.people.person_bhumika_shrestha.path`. They never search the web themselves.

#### Quality Gates — Phase 11c (Asset Acquisition)

- [ ] `MANIFEST_COMPLETE`: Every asset in the manifest has status `ready`, `failed`, or `needs_review`. No `pending` items remain.
- [ ] `COUNT_MATCHES`: `ready + failed + needs_review = total`. The math adds up.
- [ ] `FILES_EXIST`: Every `ready` asset has a file on disk at the registered path. `ls` confirms.
- [ ] `FILES_VALID`: Every `ready` image file passes `file` command check (is actually an image, not HTML). Every video passes `ffprobe`.
- [ ] `RESOLUTION_MET`: Every `ready` asset meets its `min_resolution` spec.
- [ ] `CLAUDE_VERIFIED`: Claude (the agent itself) read each person photo and context-sensitive asset, confirmed relevance. No Gemini used unless user explicitly requested video analysis.
- [ ] `FAILURES_LOGGED`: Every `failed` asset has a specific reason (not "couldn't find it" — must list sources tried and results).
- [ ] `REVIEWS_RESOLVED`: User has resolved all `needs_review` items before proceeding.

#### Anti-slack Rules (Asset-Specific)

**The count is sacred.** 100 assets in the manifest = 100 status entries in the report. An agent cannot mark the phase complete with 60/100 entries and claim the rest "weren't needed."

**Every failure needs a detailed reason.** "Couldn't find it" is NOT acceptable. Acceptable: "Searched Google Images (3 results, none matching), Wikimedia (0 results), Unsplash (0 results for 'Numa Limbu'). Tried alternate query 'Numa Limbu Chanchala transgender Nepal' — 1 result, Gemini confidence 0.3, below 0.6 threshold. Asset marked failed."

**Generate-don't-fetch is not optional.** If the asset type says `strategy: "generate"`, the agent generates it. If the agent web-searches instead, the quality gate catches the wasted time (the asset should already be ready from generation, not from a web search).

**File verification is automated, not self-reported.** The agent doesn't say "file looks good." The pipeline runs `file`, `ffprobe`, resolution check, and Gemini Vision. The agent's opinion of the file quality is irrelevant.

**Batched Gemini verification is the final gate.** After all agents report done, the main agent uploads ALL "ready" assets in batches of 10 and asks Gemini to verify. This catches cases where a fetching agent downloaded confidently-wrong images. An agent that downloaded a photo of "Bhumika Subba" instead of "Bhumika Shrestha" gets caught here.

### Phase 12: claudepipe studio (INTERACTIVE)

Launch the studio web app and Remotion Studio sidecar:
```bash
# Terminal 1: Studio web app
cd studio && PROJECT_ROOT=<project_root> npm run dev

# Terminal 2: Remotion Studio sidecar (for composition preview)
cd <project_root>/remotion && npx remotion studio --port 3002
```
Tell the user: "Studio running at http://localhost:5173 | Remotion Studio at http://localhost:3002"

**This is the most important phase.** The studio gives the user full visual control over editorial decisions. After agents process units (Phases 13–15), the studio shows Remotion composition previews — the actual composed output with all layers, not just raw footage.

#### Studio Capabilities

**Viewing:**
- **Sidebar**: Drag-drop unit reordering, right-click to insert/delete units. Creating a new unit also creates its Remotion composition.
- **Elements tab**: Per-unit footage clips with metadata, analysis summary, file drops
- **Player tab**: Two modes:
  - **Raw footage**: Frame-accurate video per clip with spatial+temporal markers, transcript subtitles. Used during initial editorial decisions (trims, splits, instructions).
  - **Composition preview**: Inline iframe to Remotion Studio (`:3002`) showing the unit's composed output with all layers (subtitles, VFX, SFX, music). Used after agents have processed the unit. "Open in Remotion Studio" button opens the full Remotion UI for detailed tweaking.
- **Precision tab**: Zoom view (1x–10x) for precise marker placement
- **Instructions panel**: Per-unit instructions textarea for Claude, marker reference list

**NLE Operations (data mutations on edit_manifest — source files untouched):**
- **Trim**: Set in/out points on a clip via drag handles. Non-destructive — original range preserved, trim range is what the exporter uses
- **Split**: Cut a clip at a point, creating two clip references from one source. Each piece has its own trim range. Transcript segments divide at the split point (time-based, no re-ASR needed)
- **Drag between units**: Move a clip (or split piece) from one unit to another
- **Delete chunk**: Mark a time range within a clip as deleted. Exporter skips these ranges. Deleted chunks are recoverable (remove from `deleted_ranges`)

**Trim enforcement:** The Remotion composition enforces all clip references to the trim range. If any timeline reference falls outside the trim, Phase 18 validation REJECTS with an error — not silently clips. `deleted_ranges` are similarly enforced. See `references/studio-instruction-protocol.md` for the data model.

**Animation flow checkbox:** Per-unit checkbox "Needs Animation". When checked:
1. The unit's footage is marked as *reference* (not content to render directly)
2. User uploads reference images/sketches via added media, or the footage itself serves as visual reference
3. User writes animation description in instructions textarea
4. Claude enters animation generation mode (Phase 13) for this unit
5. Generated animation becomes the unit's active content

**Teleprompter:** Studio generates a QR code in the header. Scanning opens `http://<local-ip>:5173/teleprompter/<unit_id>` on any local device. Shows the narration script (from Claude-generated content or user-written text in instructions) with configurable auto-scroll speed. Used when user needs to record new voiceover/narration for a unit.

**Versioning (git-based):** Each operation auto-commits `edit_manifest.json` to git. Current version = what's used for building. Previous versions browsable via git history. Restore = checkout specific version of edit_manifest. In studio, current version plays as default; previous versions accessible but clearly marked as history. Per-unit: clear indicator of which clips/version are active for the build.

**Server-authoritative editing:** All edit manifest mutations go through the Express server's `PATCH /api/edit-manifest` endpoint. The server reads the file from disk, applies the operation atomically, and writes back. Both the web UI and Claude agents use this same endpoint — no direct file writes to `edit_manifest.json`. This eliminates race conditions between the studio and concurrent agents.

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

#### Main Agent Integrity Rules

The main agent (the one spawning subagents) is subject to the SAME quality standards as subagents. These rules exist because the main agent has historically been the weakest link — downgrading user instructions before they reach subagents, optimizing for fast completion over correctness.

**1. NEVER rewrite or downgrade user instructions.** Pass the user's words VERBATIM to the subagent. If the user says "rotoscope," the agent prompt says "rotoscope" — not "rotoscope-style effect" or "approximate with CSS glow." If a task seems too hard, the subagent must fail honestly. The main agent does not get to pre-decide what's feasible.

**2. ALWAYS present a dry-run plan BEFORE spawning.** Show the user: "Here's what I'm about to tell the agent to do: [summary]." Wait for approval. This is the cheapest possible check — 10 seconds of user review prevents hours of wasted agent work producing garbage. Skip this only if the user has explicitly said to proceed autonomously.

**3. ALWAYS include the Agent Execution Protocol in the spawn prompt.** Reference the dry-run plan → execute → quality gates → failure protocol flow. Tell the agent which quality gates apply. If you don't, the agent will skip them.

**4. NEVER reduce scope when writing the agent prompt.** Common violations:
- Telling the agent "keep it simple," "use placeholders," or "approximate is fine"
- Describing 3 of the user's 5 requirements and omitting the other 2
- Rephrasing "rotoscope the person and put logos behind them" as "add some visual effects"
- Pre-deciding that a step is "too hard" and telling the agent to skip it

The subagent prompt MUST contain every requirement the user stated. If the main agent thinks something can't be done, it does NOT get to pre-filter — the subagent discovers that and reports failure. The main agent's job is to relay, not to editorialize.

**5. ALWAYS reference the edit manifest operations API.** If the studio server is running (`curl -s http://localhost:3001/api/status`), tell the agent to use `PATCH http://localhost:3001/api/edit-manifest` with typed operations. If the server is not running, fall back to writing results to `units/{unit_id}/agent_output.json`. Agents NEVER write to `edit_manifest.json` directly.

**6. Include ALL relevant reference docs — and the READ FIRST list from the phase spec.** Each phase has a `READ FIRST:` section listing the exact docs agents must read. Copy those into the spawn prompt. Key references by phase:
- **Phase 11b (Research):** `social-media-download.md`, `source-citation-style.md`
- **Phase 11c (Assets):** `social-media-download.md`, `source-citation-style.md`
- **Phase 13 (VFX):** `transition-fundamentals.md` (MANDATORY), `source-citation-style.md`, `remotion-compositing.md`, style profile JSON
- **Phase 14 (SFX):** `sfx-music-generation.md`, style profile SFX catalog
- **Phase 15 (Music):** `sfx-music-generation.md`, style profile music behavior
- **Phase 16b (Merge):** `transition-fundamentals.md` (MANDATORY), style profile pacing rules
- If the task involves animations, include `animation-style-config.md`. If effects, include what tools are available (`rembg`, SAM2, ffmpeg filters, etc.). The agent can't use tools it doesn't know exist.

**Anti-pattern example (what NOT to do):**
```
# BAD — main agent rewrote "rotoscope" to "glow effect"
"Keep animations practical — use CSS/SVG for effects, don't try to do actual ML rotoscoping.
A glow/outline effect around the person's position is fine."

# GOOD — pass user's words, let agent figure it out or fail
"User instruction: 'Rotoscope the person in marker m1 and then show the logo of claude
and blender and then final cutpro coming from behind.'
This requires actual person segmentation — use rembg, SAM2, or similar to extract
a person mask. The logos must layer BETWEEN the background and the segmented person.
If segmentation tools are unavailable, report failure — do NOT approximate with CSS effects."
```

---

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

#### Edit Manifest Operations API

**Problem:** Multiple concurrent writers (web UI + Claude agents) to `edit_manifest.json` causes last-write-wins data loss.

**Solution:** The studio Express server is the **single writer** to `edit_manifest.json`. All mutations go through `PATCH /api/edit-manifest` with typed operations. The server reads the file, applies the operation atomically, writes back. Node.js single-thread guarantee means concurrent requests are processed sequentially — no races.

**Operation format:**
```bash
curl -X PATCH http://localhost:3001/api/edit-manifest \
  -H "Content-Type: application/json" \
  -d '{"operation": {"type": "update_unit_instructions", "unit_id": "unit_001", "instructions": "..."}}'
```

**Available operation types:**
- `update_unit_order` — `{ order: string[] }`
- `update_unit_instructions` — `{ unit_id, instructions }`
- `update_unit_markers` — `{ unit_id, markers }`
- `update_unit_word_cuts` — `{ unit_id, cuts }`
- `toggle_discard_clip` — `{ unit_id, clip_id }`
- `add_unit_media` — `{ unit_id, media: { path, filename, type } }`
- `remove_unit_media` — `{ unit_id, media_index }`
- `insert_unit` — `{ unit_id, unit, after_index }`
- `delete_unit` — `{ unit_id }`
- `update_clip_trim` — `{ unit_id, clip_id, in_point, out_point, duration }`
- `clear_clip_trim` — `{ unit_id, clip_id }`
- `split_clip_at` — `{ unit_id, clip_id, time }`
- `remove_split` — `{ unit_id, clip_id, index }`
- `add_deleted_range` — `{ unit_id, clip_id, start, end, reason }`
- `remove_deleted_range` — `{ unit_id, clip_id, index }`
- `move_clip_to_unit` — `{ clip_id, from_unit_id, to_unit_id }`
- `set_claude_note` — `{ unit_id, notes }`
- `end_session` — `{}`
- `batch` — `{ operations: EditOperation[] }` (atomic batch of multiple operations)

**Response:** `{ ok: true, manifest: <full EditManifest> }` on success, `{ ok: false, error: "..." }` on failure.

**Initialization:** `POST /api/edit-manifest/init` — creates edit manifest from footage manifest if it doesn't exist, returns existing if it does.

**Agent usage (when studio server is running):**
```bash
# Single operation
curl -X PATCH http://localhost:3001/api/edit-manifest \
  -H "Content-Type: application/json" \
  -d '{"operation": {"type": "set_claude_note", "unit_id": "unit_001", "notes": "Generated logo reveal"}}'

# Batch multiple operations atomically
curl -X PATCH http://localhost:3001/api/edit-manifest \
  -H "Content-Type: application/json" \
  -d '{"operation": {"type": "batch", "operations": [
    {"type": "add_unit_media", "unit_id": "unit_001", "media": {"path": "units/unit_001/animations/logo.webm", "filename": "logo.webm", "type": "video"}},
    {"type": "set_claude_note", "unit_id": "unit_001", "notes": "Logo reveal animation generated"}
  ]}}'
```

**Fallback (when studio server is NOT running):** Agents write to `units/{unit_id}/agent_output.json` and the main agent merges sequentially. This is the legacy merge queue — use it only when the HTTP API is unavailable.

#### Merge Queue — Fallback for Offline Agents

When the studio server is not running (e.g., pure CLI pipeline execution without a studio session), agents cannot use the HTTP API. In this case:

1. **Agent writes to scoped file.** Each agent writes its results to:
   ```
   units/{unit_id}/agent_output.json
   ```
   This file contains ONLY the agent's mutations for its assigned unit — clip_edits, added_media, markers, word_cuts, instructions updates, claude_notes, new file paths, etc. Schema mirrors the relevant section of `edit_manifest.json`.

2. **Agent writes assets to unit directory.** All generated files (animations, SFX, renders) go into `units/{unit_id}/` subdirectories. No agent writes to project-root-level directories.

3. **Main agent merges sequentially.** After agents complete (or as they complete), the main agent:
   - Reads `edit_manifest.json` once
   - Reads each `units/{unit_id}/agent_output.json`
   - Applies each agent's mutations to the in-memory manifest (one unit at a time — no conflicts since scopes don't overlap)
   - Writes `edit_manifest.json` once
   - Same for `footage_manifest.json` if agents produced new clips

4. **Conflict detection.** If two agents somehow touch the same data (e.g., both modify a shared clip due to a clip move), the main agent detects the conflict and asks the user.

**Rule:** When spawning agents, check if the studio server is running (`curl -s http://localhost:3001/api/status`). If running, tell agents to use the HTTP API. If not, tell agents to write to `units/{unit_id}/agent_output.json`.

#### Agent Execution Protocol

Agents MUST NOT take the path of least resistance. When uncertain, FAIL — do not produce garbage and claim success. Every agent follows this execution flow:

##### Anti-patterns: How agents avoid hard work (and why we catch it)

These are the specific failure modes we've observed. The protocol below is designed to prevent them. If you catch yourself doing any of these, stop and course-correct.

**Scope reduction.** The user asks for 5 things. The agent does 2 of them and presents the result as complete. This is NOT the same as "failing cleanly" — failure means reporting "I couldn't do X because Y." Scope reduction means pretending X was never asked for.
- **Detection:** Step 1 requires listing every user requirement as a pass condition. Step 3 checks every one. If a requirement is missing from the plan, the plan is wrong.

**Complexity collapse.** A task requires 6 sequential steps (extract frame → segment person → generate border → animate sticker → add text → randomize entrance). The agent sees the chain, decides it's "too complex," and produces a single-step approximation (e.g., static overlay instead of animated sticker). The output looks vaguely related but misses the actual request.
- **Detection:** Step 1 requires decomposing into discrete checkpointed sub-steps. Each sub-step has its own pass condition. If the plan has fewer steps than the task requires, the agent is collapsing complexity.

**Silent substitution.** The user says "rotoscope" and the agent produces a CSS glow. The user says "pop color borders" and the agent uses a thin gray outline. The output exists and doesn't crash, but it's not what was asked for. The agent never reports a failure because it never tried the real approach.
- **Detection:** Step 0 (Research) requires understanding what the user's terms actually mean before planning. If the agent can't do what the term requires, it must report failure, not substitute.

**First-obstacle bailout.** The agent hits an error on step 2 of 6 (e.g., rembg fails on one frame). Instead of debugging, trying alternatives (SAM2, ffmpeg chromakey, manual masking), or isolating the failure, it abandons the entire task and reports "couldn't do it."
- **Detection:** Step 1 requires a fallback plan for each sub-step. Step 2 requires trying alternatives before declaring failure. A single error on one sub-step does not justify abandoning the whole task.

---

**Step 0 — Research.** Before planning, the agent MUST build situational awareness. This is not optional — an agent that skips research will produce context-free garbage.

- **Read SKILL.md** — understand the full pipeline, the manifest schemas, the phase you're operating in, the quality gates, the failure protocol. This is your operating manual.
- **Understand the phase** — which pipeline phase is this work part of? What are the inputs and outputs? What are the constraints?
- **Research the requirements** — if the user says "rotoscope," research what rotoscoping actually requires (person segmentation, mask extraction, layer compositing). If the user says "ducking," research how audio ducking works. Don't guess — look it up. Use web search, read docs, check what tools are installed.
- **Read the manifest state** — read `edit_manifest.json` and `footage_manifest.json` to understand the current state: what clips exist, what edits have been made, what markers are placed, what instructions the user wrote. Read the actual data, don't assume.
- **Check available tools** — what's installed? (`rembg`, `SAM2`, `ffmpeg` filters, Remotion, Manim, etc.) What APIs are configured? Don't assume a tool is unavailable without checking.
- **Read existing code patterns** — if there's existing animation code, match its patterns. If there's existing manifest mutations, follow the same schema.

**Step 1 — Decompose into sub-steps with pass conditions.** Based on research, write a plan that:

**1a. Lists EVERY user requirement.** Re-read the user's instructions word by word. Each distinct ask becomes a requirement. "Extract gorilla, remove background, create sticker with pop borders, random entrance with text" = 5 requirements, not 1. If your plan doesn't address all of them, it's incomplete.

**1b. Decomposes into sequential sub-steps.** Each sub-step is a concrete action with:
- What it does (specific action, not vague description)
- Which tool/API it uses (e.g., "rembg for person segmentation", NOT "some kind of effect")
- What the expected output looks like (file type, dimensions, format)
- **A pass condition** for this sub-step specifically
- **A fallback** if this sub-step fails (alternative tool, different approach)

Example decomposition for "extract gorilla from video, remove background, create sticker with pop borders, random entrance":
```
Sub-step 1: Extract gorilla frame → ffmpeg frame extraction at timestamp → PASS: gorilla_frame.png exists, correct resolution
Sub-step 2: Segment gorilla → rembg (fallback: SAM2) → PASS: gorilla_mask.png has alpha channel, subject isolated
Sub-step 3: Generate pop border → PIL/canvas stroke with style_config colors, medium width → PASS: bordered_sticker.png has visible colored border
Sub-step 4: Animate entrance → Remotion component with random position + spring animation → PASS: renders without error, sticker appears at random position
Sub-step 5: Add text overlay → Remotion <Text> component → PASS: text visible, readable, positioned near sticker
```

**1c. Defines global pass conditions** — the phase quality gates PLUS user-specific requirements. These are checked in Step 3.

**1d. States what it will NOT do** (explicit anti-patterns from SKILL.md).

The plan is written to `claude_notes[unitId]` so the main agent and user can review it. **If the plan has fewer sub-steps than the task complexity warrants, the agent is collapsing complexity** — go back and decompose further.

The plan is written to `claude_notes[unitId]` so the main agent and user can review it.

**Step 2 — Execute sub-steps sequentially with checkpoints.** Execute each sub-step from the plan in order. After each sub-step:
- Verify its pass condition before moving to the next
- If it passes: log success to `claude_notes`, continue to next sub-step
- If it fails: try the fallback for THIS sub-step (not the whole task). If the fallback also fails, log the failure and continue to the next sub-step if possible (some sub-steps may be independent). Only abandon the entire task if a critical-path sub-step fails with no alternatives.

**Critical rule: a failed sub-step does NOT justify reducing scope.** If sub-step 2 (segmentation) fails, you cannot skip sub-steps 3-5 (border, animation, text) and present the raw frame as the result. You report: "Sub-step 2 failed (rembg error: X, SAM2 not installed). Sub-steps 3-5 depend on this and could not proceed. Completed: sub-step 1 only. Remaining work requires: [specific tool/fix]."

**Never silently switch to an easier approach.** If you find yourself writing code that's simpler than the plan calls for, stop and ask: "Am I implementing what was planned, or am I taking a shortcut?" If it's a shortcut, either go back to the plan or explicitly log the deviation and why.

**Step 3 — Verify ALL pass conditions (scope check).** This is where scope reduction gets caught. Check:
1. **Every sub-step pass condition** from the plan. List them ALL — if any are missing from your verification, you reduced scope.
2. **Every global pass condition** from Step 1c.
3. **Every phase quality gate** (see below).

For each condition, write the actual check performed and the result — not just "PASS." Example: "PASS — ffprobe confirms 1920x1080 VP8+alpha WebM, 4.0s duration" or "FAIL — rembg not installed, person segmentation could not be performed."

**Scope verification:** Count the user requirements from Step 1a. Count the pass conditions you're checking. If you're checking fewer conditions than requirements, you dropped something. Go back and find what you skipped.

Results are written to `claude_notes[unitId]` with pass/fail status per condition, including a summary: "X/Y requirements addressed, Z sub-steps completed, W sub-steps failed."

**Step 4 — Handoff.** Report results to the main agent:
- If ALL conditions pass: report success with verification results
- If ANY condition fails: report FAILURE with details of what failed and why. Mark unit `status: "needs_review"`. Do NOT claim success with bad output. Do NOT produce a "simplified version" — fail cleanly.

#### Quality Gates by Phase

**Phase 13 — Animations & VFX:**
- [ ] `COMPOSITION_COMPILES`: Unit composition compiles after adding layers (`npx remotion compositions` lists it without errors).
- [ ] `RENDERS_FRAME`: `npx remotion still --gl=angle` renders at least 1 frame from the unit composition without crashing.
- [ ] `DURATION_MATCH`: Unit composition duration within 0.5s of expected. If voiceover exists, animation layer timing matches voiceover.
- [ ] `RESOLUTION_MATCH`: Composition dimensions match `style_config.json` (width/height).
- [ ] `STYLE_MATCH`: Colors used are from `style_config.json` palette (render 3 sample frames, extract dominant colors, compare).
- [ ] `LAYER_REGISTERED`: New `.tsx` layer files exist in `remotion/src/units/{unit_id}/layers/` and are imported in the unit's `Composition.tsx`.
- [ ] `CONTENT_RELEVANT`: Animation/VFX content matches the transcript/instruction context (not generic placeholder graphics).

**Phase 14 — SFX:**
- [ ] `FILE_VALID`: Each SFX audio file > 10KB. ffprobe confirms valid audio codec, sample rate, duration.
- [ ] `DURATION_MATCH`: Duration within 0.5s of requested.
- [ ] `NOT_SILENCE`: File contains actual audio content (peak amplitude > -40dB).
- [ ] `COMPOSITION_COMPILES`: Unit composition compiles after adding `SfxLayer.tsx`.
- [ ] `PLACEMENT_CONCRETE`: Every `<Audio>` in SfxLayer has concrete frame offset (NOT frame 0 unless intentional). Timing matches transition/emphasis points.
- [ ] `CONTEXT_MATCH`: SFX type matches its context — transition points → whoosh/riser, text appearance → pop/swoosh, emphasis → blip/hit. NOT random sounds at random times.
- [ ] `TIMELINE_BOUNDS`: All SFX `<Audio>` placements fall within the unit composition's duration.

**Phase 15 — Music:**
- [ ] `NOT_SPEECH`: Generated audio is instrumental music, NOT speech narration. Play first 10 seconds — if you hear words or human voice describing music, the gate FAILS. This means you used the wrong API (Gemini TTS instead of Lyria).
- [ ] `FILE_VALID`: ffprobe confirms valid audio. File size > 100KB for 30s WAV. Correct sample rate (48kHz).
- [ ] `NO_DISTORTION`: No clipping artifacts (peak amplitude < 0dBFS).
- [ ] `COMPOSITION_COMPILES`: Unit composition compiles after adding `MusicLayer.tsx`.
- [ ] `DUCKING_WORKS`: MusicLayer uses `interpolate()` with VAD-derived keyframes. Volume drops during speech segments, raises during silences.
- [ ] `STYLE_MATCH`: Music style matches user-approved brief (genre, mood, energy level).
- [ ] `API_CORRECT`: Music was generated using Lyria 2 (Vertex AI) or Lyria RealTime (Gemini API), or provided by user. NOT generated using Gemini `response_modalities=["AUDIO"]` — that is TTS and will always fail `NOT_SPEECH`.

#### Failure Protocol

When an agent cannot complete its task correctly:

1. **Do NOT produce garbage.** An empty result is better than a wrong result that downstream phases will treat as correct.
2. **Do NOT silently switch approaches.** If Lyria fails, don't fall back to Gemini TTS. Instead, report the Lyria failure and suggest alternatives.
3. **Write failure details to `claude_notes[unitId]`:** what was attempted, what failed, what the error was, what alternatives exist.
4. **Mark unit status as `"needs_review"`.**
5. **Report failure to main agent** with enough detail that the user can decide what to do (retry with different params, skip music, provide their own track, etc.).

**Main agent resolution:** When a parallel agent reports failure, the main agent attempts to resolve it before escalating to the user:
1. Read the failure details from `claude_notes[unitId]`
2. Diagnose: wrong API used? Missing dependency? Bad prompt? Malformed output?
3. If resolvable (e.g., agent used wrong API → re-run with correct API, bad prompt → improve prompt and retry): fix and re-run the quality gates
4. If not resolvable (e.g., external service down, ambiguous user intent, quality judgment call): present to the user with context and options

The user only sees failures the main agent couldn't resolve on its own. Successes and resolved failures are reported as a summary.

### Phases 13–15: Per-Unit Refinement (PARALLELIZABLE)

These phases run **independently per unit**. Launch parallel agents following the Agent Spawn Protocol above. Each agent works on its assigned unit with full global context but scoped mutations. Every agent MUST pass its phase-specific quality gates before handoff.

#### Phase 13: Animations & VFX (if needed)

**READ FIRST:** `references/transition-fundamentals.md` (MANDATORY for any transition code), `references/source-citation-style.md` (for source citation visuals — grungy highlighter on browser screenshots), `references/remotion-compositing.md` (FullVideo pattern, rotoscoping), `templates/styles/{style}/style_profile.json` (signature moves, composition patterns, typography). Assets are in `assets/` — reference by manifest ID, do NOT web-search for images.

Agents produce **Remotion `.tsx` components** that get added as layers to the unit's composition — NOT pre-rendered video files. Everything stays non-destructive until final render.

When manifest or user indicates animations/VFX needed:
- Detect from transcript ("this needs animation", "let me show you a diagram")
- Read any whiteboard/paper sketches from video frames via Claude vision
- For `audio` units: generate Remotion visuals synced to audio
- For `text_image` units: convert source material to Remotion components
- Ask user to record voiceover FIRST → pace animation to match
- **Read `style_config.json` and apply colors, fonts, dimensions**

**Agent output:** Each agent writes `.tsx` component files to `remotion/src/units/{unit_id}/layers/`. Examples:
- `AnimationLayer.tsx` — motion graphics, diagrams, Manim-rendered sequences
- `OverlayLayer.tsx` — rotoscoped masks (rembg + alpha video), logo compositing
- `TypographyLayer.tsx` — kinetic typography, lower thirds, callouts
- `SubtitleLayer.tsx` — styled subtitles from transcript data

The agent then imports these layers into the unit's `Composition.tsx` and registers them in the composition's layer stack. The composition controls layer ordering, timing, and visibility.

**Full-video compositing:** When the user wants overlays, VFX, or rotoscoping across the entire source footage, these are Remotion layers composited on top of the source — not separate renders. See `references/remotion-compositing.md` for the FullVideo pattern, rotoscoping pipeline (rembg + WebM VP9 alpha), VFX overlay system, logo animation with motion typography.

**Pre-rendered assets as Remotion inputs:** Some VFX require pre-computed assets (e.g., rembg mask sequences, alpha-channel WebM from rotoscoping). These are still generated as files but referenced by Remotion components — the component handles compositing, timing, and blending. The asset is data; the composition logic stays in `.tsx`.

**User approves each animation** by previewing the unit composition in studio (iframe to Remotion Studio) or opening the full Remotion Studio UI.

#### Phase 14: SFX Generation

Agents generate SFX audio files AND write Remotion `<Audio>` components to place them in the unit's composition.

Identify SFX candidates: cut/transition points (high confidence), speech pauses > 0.5s (medium), pitch emphasis changes (medium). **Never auto-place** comedic timing or emotional beats. Run `--dry-run` first to show user the plan. After approval, generate via ElevenLabs `text_to_sound_effects`. See `references/sfx-music-generation.md`.

**Agent output:**
1. Generate SFX audio files to `<project_root>/sfx/` (same as before)
2. Write `remotion/src/units/{unit_id}/layers/SfxLayer.tsx` — a Remotion component that places `<Audio>` elements at the correct timeline positions with volume control
3. Import `SfxLayer` into the unit's `Composition.tsx`

SFX are toggleable layers — the user can disable them from the composition without deleting files. **User approves placement.**

#### Phase 15: Background Music

**Do NOT use Gemini `response_modalities=["AUDIO"]`** — that is TTS (text-to-speech), not music generation. It produces speech narration, not instrumental tracks.

Music sources (in order of preference):
1. **User provides a track** — royalty-free from YouTube Audio Library, Artlist, Epidemic Sound, etc.
2. **Lyria 2 on Vertex AI** — GA API, generates 30-second instrumental WAV at 48kHz from a text prompt. Stitch multiple segments for full video. Uses existing GCP project.
3. **Lyria RealTime via Gemini API** — WebSocket streaming, captures longer continuous tracks. Experimental.
4. **Skip music in pipeline** — user adds music manually. Ducking keyframe data is still written to manifest.

**Agent output:**
1. Generate/acquire music audio files to `<project_root>/music/`
2. Write `remotion/src/units/{unit_id}/layers/MusicLayer.tsx` — a Remotion component with `<Audio>` and volume keyframes computed from VAD data (ducking during speech, raising during silences/transitions, fade in/out at boundaries)
3. Import `MusicLayer` into the unit's `Composition.tsx`

Different units can have different music styles. Music ducking is a Remotion `interpolate()` call driven by VAD data — fully adjustable without re-rendering. **Ask user to approve style.** See `references/sfx-music-generation.md`.

### Phase 16: Thumbnails (GLOBAL)

Pick the best frames (highest interest_score) across all units. Generate 3 thumbnail options using Pillow — bold text overlay with title. Resolution 1280×720. **User picks favorite.**

### Phase 16b: Merge Unit Compositions into Master

**READ FIRST:** `references/transition-fundamentals.md` (MANDATORY — all inter-unit transitions are built here), `templates/styles/{style}/style_profile.json` (pacing rules, music behavior for the merge).

Merge is **stitching Remotion compositions**, not rendering videos and concatenating them. The master composition imports each unit composition as a sequence — all layers remain separate and editable.

1. Create/update `remotion/src/Master.tsx` — the master composition that sequences all unit compositions
2. Each unit composition is imported as a `<Series.Sequence>` in unit order
3. Inter-unit transitions (controlled by main agent, not unit agents) are added as Remotion transition components between sequences. **Read `references/transition-fundamentals.md` before writing transition code.** Transitions must follow AE fundamentals: scale match cuts (zoom in → cut → zoom out), position match cuts (momentum direction matches across cut), glitch hard cuts (for high-contrast reveals), and 1-2 frame invert stutter at every cut point. Do NOT use `backdropFilter` — use solid overlay layers only.
4. Global music tracks that span multiple units are added as a top-level `<Audio>` layer with ducking keyframes merged from all units' VAD data
5. Register `MasterComposition` in `remotion/src/index.ts` with total duration = sum of unit durations + transitions

Back up pre-merge master as `Master.tsx.bak`. Update `pipeline_state.units_merged = true`.

**Merge rules:**
- Unit compositions are imported as-is — their internal layers (VFX, subtitles, SFX, unit-level music) are NOT flattened
- Inter-unit transitions are Remotion components wrapping adjacent unit sequences
- Global music (if any) is a separate layer on top of the master, distinct from per-unit music
- Unit order from `edit_manifest.json` determines sequence order in `Master.tsx`

**Merge output contract** (Phase 17 render depends on this):
- `Master.tsx` MUST compile without errors (`npx remotion compositions` lists it)
- Every unit composition referenced in Master MUST exist and compile independently
- Total duration of master MUST equal sum of unit durations + transition durations
- All media files referenced by any unit composition MUST exist on disk
- Trim ranges and deleted_ranges from edit_manifest MUST be respected in unit compositions

### Phase 17: Final Render

This is the only phase that produces rendered video files. Everything before this is Remotion source code — compositions, layers, components.

**Master render (full video):**
```bash
cd <project_root>/remotion && npx remotion render src/index.ts MasterComposition \
  --output="../renders/final_16x9.mp4" \
  --gl=angle --codec=h264 --concurrency=50%
```

**Per-unit render (optional, for review):**
```bash
cd <project_root>/remotion && npx remotion render src/index.ts Unit001 \
  --output="../renders/unit_001.mp4" \
  --gl=angle --codec=h264 --concurrency=50%
```

**Output formats:**
- 16:9 long-form (1920x1080, 30fps) — primary. Render `MasterComposition`.
- 9:16 long-form (1080x1920, 30fps) — uses crop keyframes. Render `MasterComposition9x16` (same layers, different viewport + crop transforms).
- 9:16 shorts (extracted key segments, < 60s each) — render individual `Short001`, `Short002` etc. compositions.

**Layer toggling at render time:** Because subtitles, SFX, music, VFX are all separate Remotion layers, the user can disable any layer before rendering. Want no subtitles? Comment out or prop-toggle `SubtitleLayer` in the composition. Want different music? Swap the `MusicLayer` audio source. No re-processing of any other layer needed.

**VFX effects available:** kinetic typography (Devanagari-first), Ken Burns zoom, background blur, rotoscoping, speed ramping, color grading, transitions (whip pan, mask reveal, glitch, dissolve), OSM maps via MapLibre GL (`OSMMap` component — see Key Rule 19), SVG boundary animations (`NepalGeoMap`). See `references/vfx-pipeline-plan.md`.

**Audio mixing:** All audio (source clips, SFX, music) is mixed in the Remotion composition via `<Audio>` components. SFX coupled to VFX events, music with VAD-driven ducking via `interpolate()`.

### Phase 18: Composition Validation + Trim Enforcement

Verify all Remotion compositions compile and are structurally correct before final render. **This is the enforcement layer — it fails the build rather than producing bad output.**

**Composition validation:**
- `npx remotion compositions` succeeds — all unit compositions and MasterComposition are listed without errors
- Each unit composition renders at least 1 frame without crashing (`npx remotion still --gl=angle`)
- All media files referenced by `<Video>`, `<Audio>`, `<Img>` components exist on disk
- Audio/video durations of source files match what the compositions expect (ffprobe verification)

**Timeline validation:**
- No clip overlaps within a composition's video track
- Inter-unit transitions in MasterComposition reference valid adjacent unit sequences
- SFX/overlay layer timing falls within the unit composition's duration
- Total MasterComposition duration = sum of unit durations + transitions

**Trim enforcement (critical):**
- Every `<Video>` or `<OffthreadVideo>` component's `startFrom`/`endAt` MUST respect the clip's `trim` range from edit_manifest
- No video component may include frames from `deleted_ranges`
- If ANY violation is found: **REJECT the build with an explicit error** listing every violation. Do NOT silently clamp or adjust — fail loudly so the user can fix the composition
- This prevents agents from accidentally including trimmed/deleted content in their `.tsx` code

Report all issues. Build cannot proceed to Phase 17 render until validation passes.

### Phase 19: YouTube Metadata (CONVERSATIONAL)

Generate YouTube metadata:
- Title, description with chapters, tags, category
- Language from `project.language`: `ne` or `ne+en` → `"ne"`, `en` → `"en"`
- Shorts metadata for each short
- **User approves before finalizing.**

See `references/youtube-metadata-spec.md`.

### Phase 20: Cleanup

Remove `tmp/` directory. Optionally remove: `frames/`, `analysis/` (manifest has the data), `units/` (use `--keep-units` to preserve). Always preserve: `raw/` symlinks, `renders/`, `footage_manifest.json`, `style_config.json`.

## User Approval Gates

Phases marked with **bold user approval** MUST pause and wait for user input:
- Phase 10: Screen recording layout choice
- Phase 11b: Unit decomposition review
- Phase 11b (research): Research brief approval (user confirms facts, selects B-roll clips)
- Phase 11c (assets): Asset manifest review (user adds/removes assets before fetching), asset dashboard review (user resolves needs_review items)
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
- `vfx-pipeline-plan.md` — VFX composition pipeline: Remotion rendering, ElevenLabs audio, editorial beats
- `crop-easing-guide.md` — 9:16 crop strategies + easing curves
- `asr-chirp-setup.md` — ASR engine setup and fallback chain
- `gemini-video-understanding.md` — Gemini Flash video analysis API, cost, capabilities and limits
- `sfx-music-generation.md` — ElevenLabs SFX + music generation options
- `animation-style-config.md` — Manim/Remotion style consistency
- `screen-recording-sync.md` — Audio cross-correlation sync
- `short-form-workflow.md` — Short-form content extraction
- `youtube-metadata-spec.md` — YouTube upload metadata format
- `nle-export-formats.md` — (deprecated) Legacy NLE export reference, kept for historical context
- `studio-instruction-protocol.md` — How Claude interprets markers, instructions, trim/split/drag/delete operations
- `pipeline-runtime-notes.md` — Operational findings: dependency gotchas, Chirp 2 location constraints, manifest format expectations between phases
- `remotion-compositing.md` — Remotion as full compositing engine: FullVideo pattern, rotoscoping (rembg + VP9 alpha), VFX overlay system, logo animation, motion typography
- `transition-fundamentals.md` — **MANDATORY** transition reference. AE-style fundamentals: pace/rhythm, cut-at-peak-movement, 1-2 frame invert stutter, momentum matching, contrast-driven hard cuts. Read this BEFORE writing any transition code.
- `source-citation-style.md` — How to visually cite sources in videos: browser screenshots with grungy highlighter markup, visible URL/portal branding, QR codes for direct access. Used during Phase 13 when presenting research sources, news articles, or factual claims.
- `social-media-download.md` — Platform download matrix: YouTube (direct), TikTok (Playwright search + yt-dlp impersonation), Facebook (Googlebot UA trick — only `/posts/` URLs work), Dailymotion (direct). Includes Nepal-specific pages (RONB, OnlineKhabar) and the cross-posting pattern for finding content across platforms.
- `source-screenshot-pipeline.md` — Technical reference for capturing source citations: Playwright at 2x Retina (`device_scale_factor=2`), cookie dismissal, `get_by_text()` bounding box extraction for highlight coordinates, grungy highlighter PIL overlay (8 random-offset passes), coordinate scaling, fallback chain. Used during Phase 11c asset acquisition.

## Remotion Project Structure

A Remotion project template lives at `remotion/` in the repo root. Phase 1 copies it into `<project_root>/remotion/` and runs `npm install`.

```
<project_root>/remotion/
  package.json              # Remotion deps (@remotion/cli, @remotion/player, react, etc.)
  remotion.config.ts        # Bundler config, webpack overrides
  src/
    index.ts                # Root — registers all compositions (unit + master)
    Root.tsx                 # Root component wrapping all compositions
    Master.tsx               # Master composition — sequences all units (created in Phase 16b)
    components/              # Shared reusable components (from template)
      VideoClip.tsx          # Trimmed <OffthreadVideo> with deleted_ranges support
      SubtitleRenderer.tsx   # Renders transcript JSON as styled subtitles
      AudioLayer.tsx         # <Audio> wrapper with volume interpolation
      TransitionLibrary.tsx  # Shared transition components (dissolve, whip pan, etc.)
    units/                   # Per-unit compositions (created dynamically per unit)
      unit_001/
        Composition.tsx      # Unit root — imports and stacks all layers
        layers/              # Agent-written components
          SubtitleLayer.tsx   # Subtitles from transcript data
          VfxLayer.tsx        # Visual effects, rotoscoping, overlays
          SfxLayer.tsx        # <Audio> SFX placement
          MusicLayer.tsx      # <Audio> music with ducking keyframes
          AnimationLayer.tsx  # Motion graphics, diagrams
      unit_002/
        Composition.tsx
        layers/
          ...
    lib/
      types.ts               # Shared types (clip references, keyframes, etc.)
      utils.ts               # Frame math, interpolation helpers
```

**Template provides:** shared components, types, config. **Agents provide:** unit-specific `.tsx` layers.

**Studio integration:** `npx remotion studio --port 3002` runs from `<project_root>/remotion/` as a sidecar. Studio embeds via iframe for inline preview. "Open in Remotion Studio" links directly to `:3002`.

**Rendering:** Only Phase 17 calls `npx remotion render`. All prior phases produce `.tsx` source code, not video files. **`--gl=angle` is REQUIRED on every `remotion render` and `remotion still` command** — the default SwiftShader backend cannot handle MapLibre GL's WebGL rendering. Without this flag, map compositions will render as blank or crash.

## Key Rules

1. **Manifest is truth** — all state lives in `footage_manifest.json` (source data + global timeline) and `edit_manifest.json` (user edits)
2. **Never modify originals** — `raw/` contains symlinks or denoised muxed copies (Phase 3 Step 4), originals stay at source_path
3. **Easing is NEVER linear** — always BEZIER, SINE, EXPO, BACK, ELASTIC, BOUNCE, or CONSTANT
4. **Language from manifest** — `project.language` drives ASR codes, vision prompts, and YouTube metadata. Default `ne+en` if unset
5. **User has final say** — at every approval gate, present options and wait
6. **Style consistency** — always read `style_config.json` for colors/fonts/dimensions
7. **Global timeline, scoped units** — one timeline for the whole video. Units are logical groupings within it. Parallel agents read the full context but only write to their assigned unit
8. **Agent spawn protocol** — every parallel agent gets full global context + all agent assignments. Mutations scoped to assigned unit only. No exceptions.
9. **Trim is sacred** — user-set trim ranges and deleted chunks are enforced by the exporter. No agent, no phase, no script can override trims. Phase 18 validation rejects builds that violate trims.
10. **Unit = concept** — one unit represents one topic/concept, not one clip. A clip covering two topics becomes two units. Five takes of the same intro is one unit with the best take selected.
11. **Scripts are optional** — reference implementations in `scripts/` can be used or bypassed; do what's most effective for the phase
12. **Composition is the working document** — each unit has a Remotion composition (`.tsx`) that evolves through the pipeline. Agents add layers to compositions, never produce pre-rendered video files (except pre-computed assets like rembg masks). Rendering happens once at the very end (Phase 17). This means any layer (subtitles, VFX, SFX, music) can be toggled, swapped, or removed without re-processing anything else.
13. **Agents write `.tsx` components** — per-unit agents produce actual Remotion component code in `remotion/src/units/{unit_id}/layers/`. Quality gates verify compositions compile and render correctly.
14. **Transitions follow AE fundamentals** — MANDATORY reading: `references/transition-fundamentals.md`. Every transition must: (a) cut at peak movement, not at rest, (b) use spring/bezier easing, never linear, (c) include 1-2 frame invert stutter at cut points for clean contrast, (d) match momentum direction across the cut (outgoing direction = incoming direction), (e) use contrast (light→dark or color shifts) for hard cuts. Do NOT use `backdropFilter` in Remotion — it renders incorrectly in headless Chrome. Use solid overlay layers instead.
15. **Assets are fetched upfront, not mid-production** — Phase 11c generates an asset manifest and fetches everything BEFORE agents start Phase 13-15 work. No agent should ever web-search for an image during composition work. All assets are in `assets/` with paths registered in `assets/manifest.json`. Agents reference assets by manifest ID.
16. **Transcripts are free, Gemini video is not** — YouTube transcripts (`yt-dlp --write-auto-subs`) are the primary research source. Claude reads transcripts directly. Gemini video analysis is used ONLY when the user explicitly asks to analyze visual content. Never auto-escalate to Gemini for tasks Claude can do (reading images, verifying file types, comparing photos to descriptions).
17. **Claude verifies, Gemini is last resort** — the agent (Claude) is the primary verifier for all assets. It reads downloaded images directly, checks quality, confirms identity. Gemini is used only when the user explicitly requests video analysis or when Claude genuinely cannot determine relevance (and even then, ask the user first).
18. **Style profile drives everything** — when `project.style` is set, read `templates/styles/{style}/style_profile.json` at the start and let it inform every decision: script structure (pacing patterns), asset types (what to fetch), composition patterns (layer stacking), SFX (catalog prompts and placement), music (ducking rules, silence drops), typography (fonts, colors, animations), and transitions. Don't invent a style from scratch when a profile exists. The three-pass analysis (Phase 0) is the ONLY phase where Gemini video analysis is justified as a default — it's a one-time investment per style.
19. **OSM Maps via MapLibre GL** — ALL map shots MUST use the `OSMMap` component (`src/components/OSMMap.tsx`) with MapLibre GL + CartoDB Dark Matter vector tiles. Never use static SVG maps for geographic accuracy — SVG maps have no coordinate system and pins land on wrong locations. Camera keyframes support smooth animated zooms from country to street level with bezier easing. Use presets: `SOUTH_ASIA`, `NEPAL_OVERVIEW`, `KATHMANDU_CLOSE`, `MAITIGHAR` (or define custom ones). City coordinates available in `src/lib/nepal-geo.ts` (75 district HQs). JH dark style overrides applied automatically: dark navy background, bright labels, visible borders, warm gray roads. Pins use MapLibre markers with spring entry animation and glow pulse. The `NepalGeoMap` component (GeoJSON renderer) is still valid for animated sequences like election floods and province dissolution — it renders province/district boundaries as SVG paths with animation support. Always layer `FilmGrainOverlay` + `Vignette` on top of map shots (standard JH layer stack). **`--gl=angle` is REQUIRED on every `remotion render` and `remotion still` command** — default SwiftShader cannot handle MapLibre's WebGL rendering.
