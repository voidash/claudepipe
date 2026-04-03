---
name: footage
description: Research, script, compose, and render video content. Spec-driven pipeline with parallel subagents, per-beat validation, and narration-synced timing. Handles Nepali/English content, 16:9 long-form and 9:16 shorts.
user_invocable: true
---

# /footage — Video Creation Pipeline

You are creating a VIDEO, not writing software. Code that compiles is not the same as a good video. You must SEE your output (render frames, read them, check against spec) after every write. If you haven't looked at what you produced, you haven't finished the task.

## Two Laws

**1. NARRATION DRIVES THE VIDEO.** The narrator's voice is the timeline. ASR word timestamps determine when every visual element appears. Composition spec timing is speculative until narration exists. When narration arrives, everything remaps to real word timestamps. You never warp, stretch, or reposition narration — you reposition everything else around it. Also keep in mind that bunch of footage or bunch of audio is not narration. A clean narration comes from a pipeline.

**2. SPEC IS THE SINGLE SOURCE OF TRUTH.** The composition spec (`sequence_spec.json`) defines every beat, every layer, every asset, every transition. Remotion code is DERIVED from the spec. To change the video, change the spec first, then update the code. Never modify code without updating the spec. Never let code drift from spec.

## Two-Level Spec System

**Level 1 — Rough spec** (`spec/rough_spec_v1.md`, ~300 lines but can be more if required. Just make sure it covers all the outline). Human-readable. Section-level: what happens, key assets, mood, pacing notes. The creator reads and approves ONLY this. Written during research phase.

**Level 2 — Detailed spec** (`spec/sequence_spec_v1.json`). Machine-readable. Per-beat: layers with full specifics (natural language — colors, sizes, pivots, easing, animation behavior, validation criteria). Custom visuals get sub-specs within the layer description. Claude expands Level 1 into Level 2. Codex/agent reviews Level 2. Creator never reads Level 2.

The detailed spec contains:
- Beat ID, name, time range, duration
- Layers as natural language with specifics (not vague — colors, dimensions, pivot points, animation type, easing, what to validate)
- Asset references per beat
- Transition in/out descriptions
- Section markers
- Rules block (min layers per frame, asset requirements, no-emoji, etc.)
- `timing_source`: `"speculative"` or `"narration"` — clearly marks whether timing is mapped to real ASR timestamps
- `codex_review_applied` + `codex_fixes` array

When timing is speculative, it MUST be commented in code. When narration arrives, the spec remaps and `timing_source` flips to `"narration"`.

## Spec → Code Flow (non-negotiable)

```
Creator says: "Make frame 2314 background darker and add a protest count chip"
  → Step 1: Figure out what Beat does frame 2314 relates to . Let's suppose it's B12
  → Step 2: Update sequence_spec.json (B12 layers modified)
  → Step 3: Update B12.tsx code to match new spec
  → Step 4: Render frame, validate visually

NEVER:
  Creator says: "Make frame 2314 darker"
  → Speculate it might be some beat and Edit B12.tsx directly
  → Spec is now stale
```

If validation discovers something that needs to change beyond the spec (e.g., text unreadable on light background, needs contrast overlay), update the spec to reflect reality and log in `spec/changelog.md`.

## Style Philosophy: Crafted, Not Generated

The video must look like a human editor made deliberate choices — not like AI assembled elements from a template. The specific color palette, typography, and density mode are decided PER VIDEO during the research phase and defined in the spec. The principles below are universal.

### Visual Hierarchy (every frame)

Every frame has exactly three tiers:
1. **Hero** (1 element) — dominant. Largest, brightest, most contrast. This is what the viewer sees first.
2. **Support** (2 elements) — context. Medium size, connects to the hero, gives meaning.
3. **Atmosphere** (3+ elements) — texture. Grain, accent lines, faint backgrounds, breathing glow. The viewer FEELS these without consciously noticing them.

The viewer's eye travels: hero → support → atmosphere. If you can't identify the hero in a rendered frame, the composition is wrong.

Minimum 3 meaningful elements per frame. Accent bars, glow, and grain do NOT count toward the 3 — those are atmosphere.

### Motion

**Ambient (always on, subconscious):**
- Film grain shifting
- Very slow parallax on background layers (0.5-1px/second drift)
- Subtle breathing glow on accent elements (opacity 0.8↔1.0, 3s cycle)
- Ken Burns on EVERY photo — a static photo on screen looks dead

**Intentional (at editorial beats, draws the eye):**
- Elements entering or exiting
- Text appearing with spring/slam
- Counters animating
- Photos scaling to hero size
- Data chips sliding in

Ambient is the heartbeat (constant). Intentional is the punctuation (sparse, meaningful). If everything moves intentionally all the time, nothing stands out.

### Anti-AI Rules (non-negotiable)

These are researched, documented visual fingerprints that make content identifiable as AI-generated. Ban all of them. Validation MUST check for these.

**Color:**

| Pattern | What to do instead |
|---------|-------------------|
| Purple/indigo as default accent (`indigo-500`, `#5E6AD2`) | Choose colors from the video's topic and mood. Politics ≠ tech ≠ culture. No default palette. |
| Pink-to-purple gradient transitions | Gradients must use the spec's declared palette, grounded in content context. |
| Soft corporate gradients as "premium" decoration | Use textured backgrounds: real photos with overlays, noise, grain. Gradients earn their place or don't exist. |
| Dark mode + neon green/cyan accents | Accent colors must relate to the content (e.g., national colors, brand colors, emotional temperature). |
| Oversaturated everything (thumbnails) | Natural contrast. Dramatic ≠ neon. Grade for mood, not attention-hacking. |

**Typography:**

| Pattern | What to do instead |
|---------|-------------------|
| Same 5 fonts forever (Inter, Roboto, Poppins, Montserrat) | Choose fonts per-video that match the tone. Display fonts for titles. Devanagari for Nepali content. |
| Gradient text on dark backgrounds | Solid text colors with proper contrast. If text needs emphasis, use weight/size, not gradient fills. |
| Uppercase eyebrow labels with letter-spacing above everything | Section kickers only where editorially motivated. Not decorative. |
| Random word bolding without emphasis function | Bold/highlight ONLY the word the viewer must remember. Every emphasis must be earned. |

**Animation and Motion:**

| Pattern | What to do instead |
|---------|-------------------|
| Uniform springs (same damping/stiffness everywhere) | Vary per element: heavy elements overshoot less, light elements bounce more. A title slams differently than a data chip. |
| Uniform timing (everything 300-500ms) | Vary by importance: hero = 400-600ms, support = 200-300ms, atmosphere = continuous. |
| No anticipation or follow-through | Before a slam: 2-frame scale-down (anticipation). After: 3-frame overshoot + settle (follow-through). |
| Same-speed Ken Burns on every photo | Vary speed by content: slow push on emotional, faster on energy. Some photos don't need motion. |
| Camera movement without motivation | Every move serves narrative: push-in for intimacy, pull-out for revelation, pan for connection. |
| Linear or simple ease-in-out curves | Use spring, bezier, expo, back, elastic. Each element gets its own curve based on weight and purpose. |
| Cross dissolve as universal transition | Match transition to editorial intent: hard cut for energy, dissolve for time passage, push for connection. |

**Composition and Layout:**

| Pattern | What to do instead |
|---------|-------------------|
| Centered, symmetrical framing as default | Use asymmetry, rule-of-thirds, negative space for tension. Center only when symmetry serves meaning. |
| Three-column grids for everything | Layout follows content hierarchy. If one thing matters most, give it 70% of the frame. |
| Overpadded layouts (excessive spacing as "premium") | Tight, intentional spacing. Dense when dense, sparse when sparse. Space is a choice, not a default. |
| Same spatial arrangement on consecutive beats | No two adjacent beats use the same layout. Vary hero position, support placement, text location. |
| Floating elements with no spatial relationship | Ground elements: overlap, connect with lines/shadows, shared anchors, depth layers. |
| Oversized border-radius everywhere (20-32px pills) | Vary: sharp for data/evidence, slight rounding for organic, mixed within a frame. |

**Texture and Surface:**

| Pattern | What to do instead |
|---------|-------------------|
| Monochrome flat fills on every element | Subtle internal texture: noise at 3-5% opacity, micro-gradient, grain overlay. Nothing is perfectly flat. |
| Digital sterility (no grain, no noise, no imperfection) | Film grain + vignette as baseline. Sensor noise on dark backgrounds. |
| Glassmorphism / frosted panels / `backdrop-filter` | Solid overlays with opacity. `backdropFilter` also banned for Remotion rendering (kaleidoscope artifacts). |
| Decorative blobs and aurora effects as filler | Backgrounds are real photos with grades, or intentional solid colors. No decorative SVG blobs. |
| Heavy drop shadows (`0 24px 60px rgba(0,0,0,0.35)`) | Subtle, physically motivated shadows. Light source consistent across all elements in the frame. |
| Perfect geometry everywhere | Slight rotation (0.5-1deg) on accent elements. Imperfect alignment for organic feel. |

**Pacing:**

| Pattern | What to do instead |
|---------|-------------------|
| Equal-length beats throughout (metronomic) | Variable pacing: cluster fast beats (1.5-2s) then slow (5-6s). Match narration rhythm. |
| Constant visual pressure (no breathing room) | Deliberate stillness before key moments. Let the viewer absorb. |
| Cuts on schedule rather than on story beats | Every cut motivated by narrative: topic shift, emphasis, reveal, energy change. |
| Flat pacing (no editorial arc) | Open tight (fast cuts) → deepen (slower) → punch (pattern break) → close (decelerate). |

**The meta-rule:** AI produces the statistical median of its training data — recognizably safe, recognizably bland. Human work has a POINT OF VIEW. It makes bold choices: unusual compositions, aggressive cuts, intentional asymmetry, motivated silence. If your output could have been produced by averaging 1000 YouTube videos, it's AI slop. If it couldn't, it's crafted.

### Text Rules

Text appears on screen ONLY when:
- It's a data point (number, stat, name) the viewer needs to READ and REMEMBER
- It's a direct quote shown alongside the person who said it
- It's a label identifying something in frame (lower third, location tag)
- It's the title/hook slam (first 2-3 seconds)

Text does NOT appear when:
- The narrator is already saying the words (redundant — subtitles are the exception, they serve accessibility)
- It's describing a concept (show a visual metaphor instead)
- It's a transition (use motion/audio, not a text card)
- Claude can't think of a visual ("I'll put the keyword on screen" is the lazy fallback)

**The test:** for every text element, ask: "If I mute the video, does this text tell the viewer something they can't get from the visuals alone?" If yes, it earns its place. If no, replace with a visual.

**Validation check:** after rendering a frame, if text layers outnumber visual layers → flag as "text-heavy, needs visual replacement."

### Pattern Breaks

Set up a visual rhythm (3-4 beats with similar structure), then BREAK it on the beat that matters most. The break says "THIS is the important part" without words.

- 2-3 pattern breaks per video, at the biggest moments only
- Marked in spec as `"break": true`
- The break beat MUST be visually distinct from its neighbors: different layout, different motion, different scale, different color temperature
- Examples: steady dark composition → sudden full-bleed bright photo. Slow Ken Burns → hard cut with flash. Building diagram → smash to real-world footage.

### Content-Adaptive Density

The spec declares the mode per section. Not every section of a video has the same visual weight.

| Mode | When | Visual approach |
|------|------|----------------|
| **Dense** | Politics, data, investigation, evidence | Lots of layers, real documents/screenshots, data viz, multiple support elements |
| **Simple** | Personal stories, direct address, emotional moments | Speaker carries it. Minimal graphics. Let the face and voice do the work. |
| **Building** | Explanations, processes, systems, how-things-work | Diagrams that assemble piece by piece. Elements arrive as the narrator introduces them. |

### Footage-Specific Style

When the video includes camera footage of the creator:
- **Ken Burns** on talking head: slow push toward speaker during key statements
- **Conversational push-in**: gradual, not jarring
- **Music silence before key statements**: background music drops to ZERO 0.5-1s before the narrator delivers the punch line. The silence IS the emphasis.
- **Data as visualization, never as text**: "25% GDP = remittance" is a bar chart or visual, not text on screen.

### Maps

When the content references geographic locations, use the `OSMMap` component (MapLibre GL + CartoDB Dark Matter tiles). Never use static images for maps that need geographic accuracy. Camera keyframes for animated zooms. City coordinates available in `src/lib/nepal-geo.ts` (75 Nepal district HQs). `--gl=angle` required for MapLibre rendering.

`NepalGeoMap` (GeoJSON/SVG renderer) is for animated boundary sequences only (elections, province dissolutions) — not for pin-accurate maps.

### Color and Typography

Decided per video during the research phase. Defined in the spec's rules block. Not locked to any default palette. Claude decides typography based on content (Devanagari-first for Nepali content). The spec must explicitly state the palette and font choices so all subagents are consistent.

## Quick Start

When the creator invokes `/footage`, ask:

1. **"What's the topic?"** — Brief description of what the video is about.
2. **"What language?"** — Nepali (`ne`), English (`en`), or mixed (`ne+en`). Store as `project.language`. Drives ASR language codes, vision prompts, YouTube metadata. Default: `ne+en`.
3. **"What style?"** — Use a saved style profile (e.g., `johnny_harris`) or describe the visual direction. If custom reference videos are provided, run Phase 0.
4. **"Where are the source files?"** — Paths or glob pattern to footage, audio, images, or text. Can be provided later (after research phase).
5. **"Any special instructions?"** — e.g., "this needs heavy animation", "keep the whiteboard section", "shorts only"

Then run the pipeline phases below. The Remotion project at `remotion/` in the repo root is shared across all projects — individual projects reference it. Run `npm install` there if deps are missing.

## Remotion Terminology

Use these terms precisely — misuse leads to wrong code structure:

- **Composition** = a renderable unit with id, dimensions, fps, duration. Registered with `<Composition>`. Each beat (B01, B02, ...) is a composition. `Master` and `MasterShort` are compositions.
- **Sequence** = a positioned time layer within a composition. A single animated element — text reveal, photo with Ken Burns, data chip, counter. Positioned with `<Sequence from={} durationInFrames={}>`. Multiple sequences overlap (later renders on top).
- **Layer** = a conceptual grouping in the spec (hero, support, atmosphere). In code, layers are sequences or groups of sequences within a composition.

## Pipeline Phases

### Phase 0: Style Extraction (optional, run once per new style)

Skip if using a saved style profile (e.g., `johnny_harris`). Only run when the creator provides new reference videos.

Three-pass Gemini analysis on reference video:
1. **Blind discovery**: list every visual and audio technique (80+ observations)
2. **Pattern extraction**: duration, easing, sync relationships, SFX catalog, music behavior, 5 signature moves
3. **Composition sequences**: frame-level layer timelines for key moments

Output: `templates/styles/{style_name}/style_profile.json` + analysis docs.

### Phase 1: Research

Inputs: topic from creator, /last30days skill, web research, creator-provided material.

**Research process:**
1. Use `/last30days` for recent coverage across Reddit, X, YouTube, TikTok, news
2. Web search for depth — facts, timelines, key figures, controversies
3. Search YouTube for existing video coverage — extract transcripts with `yt-dlp --write-auto-subs`
4. Search Facebook/TikTok for viral clips (Nepal content arrives on Facebook FIRST, YouTube lags). Use Playwright for TikTok, Googlebot UA for Facebook. See `references/social-media-download.md`
5. Read ALL transcripts — Claude reads them directly, costs nothing
6. Capture source screenshots with Playwright for citation visuals. See `references/source-citation-style.md` and `references/source-screenshot-pipeline.md`

**Five deliverables:**

1. **`spec/narration_text.txt`** — long-form teleprompter script. Clean paragraphs, no markers, no formatting. Creator reads this aloud.

2. **`spec/shorts/narration_shorts.txt`** — short-form teleprompter script. Self-contained story with teaser for full video. Punchier, more energy, tighter pacing. Up to 2 minutes.

3. **`assets/asset_list.json`** — exhaustive. Can be 1000+ entries. Per entry:
   ```json
   {
     "id": "protest_hrw_student_march",
     "type": "photo|video_clip|svg|flag|texture|map|screenshot|icon",
     "query": "what to search for",
     "context": "why this asset matters, what it shows",
     "needed_for": ["B12", "B13", "S03"],
     "source_hints": ["HRW Nepal 2024 report", "likely on Facebook first"],
     "priority": "must_have|nice_to_have",
     "status": "pending"
   }
   ```
   More is better. Over-generate, validation filters later.

4. **`spec/rough_spec_v1.md`** — long-form rough spec (~300 lines). Human-readable. Per section: what happens, key assets, mood, beat count estimate. Creator approves this.

5. **`spec/shorts/rough_spec_v1.md`** — short-form rough spec. Same format, shorter. Creator approves.

**Research checklist** (`research/checklist.json`): every research task tracked with status and notes. Nothing gets lost.

**Creator approval gate:** creator approves narration scripts + both rough specs before proceeding.

### Phase 2: Composition Spec

Inputs: approved rough specs + narration texts + asset list.

**For BOTH long-form and short-form (parallel):**

1. Claude expands rough spec → detailed `sequence_spec_v1.json`
2. Every beat gets layers with full natural language specifics:
   - Colors (hex codes), sizes (px), positions (anchor + margins)
   - Animation type, easing curve, duration, pivot points
   - For custom SVGs: element descriptions, what to draw, what colors, what to animate, where to place
   - Validation criteria per layer: what should be visible in rendered frame
3. Every beat must reference at least 1 real asset (no assetless beats)
4. Minimum 3 meaningful layers per frame (accent/glow/grain don't count)
5. Every beat-to-beat join has an explicit transition type
6. **Every `ready` asset in `assets/manifest.json` must appear in at least one beat.** After spec generation, diff the asset manifest against spec asset references. Any `ready` asset not referenced = spec is incomplete. Either use it or explicitly justify why it's unused. Assets were downloaded for a reason — the spec must deliver on that reason.

**Review loop:**
```
Claude drafts detailed spec
  → Codex CLI reviews (or agent review)
  → Claude revises based on review
  → Repeat until reviewer passes
```

**Codex review prompt MUST include:**
- Full narration script (for context)
- Full asset list (to check asset utilization)
- Specific checks: layer count per beat, **asset utilization (every `ready` asset used in at least one beat)**, transition coverage, no template repetition, receipts vs described-but-invisible text, visual pacing
- Open-ended: "What's missing? What feels lazy? Where would a viewer get bored?"

Invoke Codex CLI (must be in PATH — install via `bun install -g @openai/codex` or `npm install -g @openai/codex`):
```bash
codex exec "Review this sequence spec JSON for [video title]. [Full context + checks + questions]. File: spec/sequence_spec_v1.json"
```

**Spec versioning:** v1 (speculative timing) → v2 (narration-mapped) → v3+ (changes). `spec/changelog.md` tracks what changed and why.

### Phase 3: Asset Acquisition

Inputs: `assets/asset_list.json` + spec asset references (both long-form and short-form, shared pool).

**Parallel agents by asset type:**

| Agent | Assets | Tools |
|-------|--------|-------|
| A | Person photos | Web search → download 5 per person → Claude verifies identity → rembg for cutouts |
| B | Flags, emblems, icons | Known URLs / Wikimedia / PIL generation |
| C | Video clips | `yt-dlp --download-sections`, Facebook via Googlebot, TikTok via Playwright |
| D | Textures, overlays | PIL / ffmpeg generation (grain, paper, light leaks) — ALWAYS generated, never fetched |
| E | Source screenshots | Playwright capture at 2x Retina, QR code generation |

**Validation per asset type:**

- **Photos**: Claude reads downloaded image. Checks: correct person? Clean background for cutout? Appropriate context (not casual photo for a minister)?
- **Video clips**: download → `yt-dlp --write-auto-subs` → Claude reads transcript → "Does this clip actually show what the spec needs?" This is the 60% failure rate fix. Transcript verification is mandatory for every video clip.
- **Generated assets** (flags, textures, grain): generate programmatically with PIL/ffmpeg. Never web search for these.
- **All assets**: `file` command confirms format (catches HTML-disguised-as-PNG), ffprobe/PIL for resolution check, size check.

**Facebook-first for Nepal content:** Nepal viral clips appear on Facebook reels 1-3 days before YouTube. When searching for recent Nepal footage, search Facebook (RONB, OnlineKhabar pages) FIRST, YouTube second. See `references/social-media-download.md`.

**Asset checklist** (`assets/manifest.json`): every asset ends as `ready`, `failed`, or `needs_review`. The count is sacred: `ready + failed + needs_review = total`. No missing entries.

**Dashboard presented to creator:** X/Y ready, failures with specific reasons (sources tried, results), items needing creator input.

### Phase 4: Narration + Timing Remap

**Narration recording:**
- Option A: creator records at studio → provides footage files
- Option B: edge-tts generates placeholder audio → dummy image for camera footage slot → creator records later and re-syncs

**ASR (Chirp 2) — non-negotiable rules:**

| Rule | Detail |
|------|--------|
| Engine | Chirp 2 only. Fallback: Gemini → Whisper |
| Regions | `us-central1`, `europe-west4`, `asia-southeast1` ONLY |
| Language | Single code from `project.language`: `ne-NP` for Nepali/mixed, `en-US` for English. NEVER `auto` (misidentifies Nepali as Latin). NEVER multi-language codes. |
| Sync limit | 60 seconds max |
| Chunking | Clips > 55s: chunk at 50s with 5s overlap. Align chunks by matching identical word sequences at boundaries, keep higher-confidence version. |
| Coverage check | After chunk merge: total transcribed duration must be ≥ 80% of clip duration. If not, re-run with 30s chunks on gaps. |

See `references/asr-chirp-setup.md` for setup details.

**Timing remap:** ASR word timestamps → beat timings in spec. For each beat, the spec already has narration words that map to it (from the narration script). Find those words in ASR output, use their timestamps.

Output: `spec/sequence_spec_v2.json` with `timing_source: "narration"`. Same for shorts spec.

**Re-sync when creator records later:** When real narration replaces TTS placeholder, re-run ASR → remap spec to new timestamps → update code. The spec is the single source of truth — code reads timing from spec, so timing changes propagate automatically through `lib/spec.ts`. Layer/animation code doesn't change, only timing.

### Phase 5: Footage Processing

When the creator provides camera footage (the common case). Even without camera footage, if there's narration audio, ASR still runs (Phase 4 handles that).

**Step 0 — Scan & classify:**

Run `ffprobe -v quiet -print_format json -show_format -show_streams` on each source file. Classify as `camera` vs `screen_recording` based on: resolution patterns (exact 1920x1080 at constant framerate → likely screen), codec (h264_nvenc/screen codecs → screen), absence of audio → screen, camera model metadata → camera. Populate `footage_manifest.json` with clip metadata (codec, resolution, fps, duration, audio channels). This manifest is the media inventory for all downstream phases.

**Instruction footage detection:** Some clips are the creator recording instructions for Claude (explaining on a whiteboard what to build, describing an animation). These are NOT content for the final video — they are INPUT. Detection heuristics:
- Speaker references Claude/AI: "Claude needs to animate this", "use Remotion", "rotoscope the person"
- Speaker describes what they WANT built, not showing something that already exists
- The clip's transcript content matches a spec beat's animation description

Do NOT ask the creator which clips are instructions. Read the transcript. If someone says "Claude should do X with Remotion", that's obviously not YouTube content. Mark instruction clips in the footage manifest as `type: "instruction"`.

**Step 1 — Ingest + compression:**

OBS recordings are typically HEVC at extreme bitrates (70+ Mbps for 1080p). Compress on ingest:
```bash
# OBS HEVC → H.264 CRF 23 (visually identical, ~90% smaller)
ffmpeg -i "raw_recording.mp4" \
  -c:v libx264 -crf 23 -preset medium \
  -c:a copy -movflags +faststart \
  "footage/compressed/{clip_id}.mp4"
```
Original preserved in `footage/raw/`. Camera footage (GoPro, phone) is usually already reasonable bitrate — compress only if > 30 Mbps.

**Step 2 — Proxy generation:**
```bash
# 720p proxy for all editing/validation work
ffmpeg -i "footage/compressed/{clip_id}.mp4" \
  -vf "scale=1280:720" \
  -c:v libx264 -crf 28 -preset fast \
  -c:a aac -b:a 128k \
  "footage/proxy/{clip_id}_proxy.mp4"
```

**Step 3 — Audio extraction + denoising:**
```bash
# Extract 48kHz WAV (DeepFilterNet expects 48kHz)
ffmpeg -i <source> -vn -acodec pcm_s16le -ar 48000 -ac 1 audio/{clip_id}.wav

# Denoise with Rust CLI (NEVER use deepfilternet pip package — it's broken)
deep-filter audio/{clip_id}.wav --output-dir footage/denoised/

# Downsample for ASR
ffmpeg -i footage/denoised/{clip_id}.wav -ar 16000 footage/denoised/{clip_id}_16k.wav

# Mux denoised audio back into video
ffmpeg -i footage/compressed/{clip_id}.mp4 -i footage/denoised/{clip_id}.wav \
  -c:v copy -map 0:v:0 -map 1:a:0 -shortest footage/compressed/{clip_id}.mp4
```

**Step 4 — ASR on all clips** (same Chirp 2 rules as Phase 4).

**Step 4b — VAD + Pitch analysis:**

Run Silero VAD for speech/silence segmentation and librosa pYIN for pitch emphasis points on all clips. This data is used downstream for:
- Music ducking (VAD tells when speech is active → duck music)
- SFX placement (silence gaps and pitch peaks are natural SFX insertion points)
- Retake detection (long silence + restart = retake boundary)
- Clean footage pass (dead silence detection)

```bash
python3 scripts/run_vad_pitch.py <project_root>
```

Output: `analysis/vad/` and `analysis/pitch/` directories. Update `footage_manifest.json` with `clip.vad` and `clip.pitch`.

**Step 5 — Retake detection (multi-pass, MANDATORY):**

This is the #1 pain point. Never trust ASR alone. Never rush through this.

**Pass 1 — Keyword search on full transcript:**
Search for: `"retake"`, `"रिटेक"`, `"री टेक"`, `"रीटेक"`, `"sorry"`, `"सोरी"`, `"shit"`, `"let me retake"`, `"once more"`, `"one more time"`, `"फेरि"`, `"फेरि गरौं"`

The creator consistently says the English word "retake" before restarting.

**Pass 2 — Repeated content detection:**
Compare transcript segments across the full transcript. If the same content appears twice (LLM semantic comparison, similarity > 0.7), the earlier version is the failed take.

**Critical cross-clip case:** Clip N ends mid-sentence with a mistake. Clip N+1 starts with "retake" and re-does Clip N's ending, then continues with new content.
- Extract last 30s of Clip N transcript + first 30s of Clip N+1 transcript
- LLM comparison: does N+1's opening repeat/fix N's ending?
- If yes: mark divergence point in N, pickup point in N+1
- The retake preamble in N+1 (the "retake" keyword + settling time) is cut

**Pass 3 — Audio pattern detection:**
Long silence (> 3s) followed by speech restart = likely retake boundary. Cross-reference with Pass 1 and 2 hits using VAD data.

**Pass 4 — Gemini Flash video scan (if passes 1-3 are inconclusive):**
Upload clip. Ask: "Find moments where the speaker stops, shows frustration, or restarts their speech."

**Retake report** presented to creator before any cutting:
```
RETAKE REPORT:
┌─────────────────────────────────────────────────┐
│ Clip A (take_05.mp4) — 186s                     │
│ ✓ Use: 0:00 → 2:27 (good content)              │
│ ✗ Cut: 2:27 → 3:06 (fumbled ending)            │
│                                                  │
│ Clip B (take_06.mp4) — 142s                     │
│ ✗ Cut: 0:00 → 0:08 ("retake" + settling)       │
│ ✓ Use: 0:08 → 0:34 (fixes clip A's ending)     │
│ ✓ Use: 0:34 → 2:22 (new content)               │
│                                                  │
│ Final stitch: A[0:00→2:27] + B[0:08→2:22]      │
└─────────────────────────────────────────────────┘
```

Creator approves cuts → `analysis/retake_report.json`.

**Step 6 — Clean footage pass:**

After retakes are resolved, second pass catches remaining issues:

| Check | Threshold | Action |
|-------|-----------|--------|
| Dead silence | > 3s gap, no speech | Flag with timestamp (might be intentional pause) |
| Low ASR confidence | < 0.5 per segment | Flag as potential mumbling |
| Audio clipping | Peak > -1dB after denoise | Flag |
| Repeated false starts | "So the—" "The—" "What I—" within 5s | Flag as fumbling |

Output: `analysis/clean_pass_report.json`. Creator reviews which to cut.

**Step 7 — Spec remap** to real footage timing → `spec/sequence_spec_v3.json`.

### Phase 6: Build

Generate Remotion `.tsx` code FROM the detailed spec. Code reads timing from spec JSON — timing changes in spec require no code changes.

**Per-beat file structure:**
- Each beat = one file: `remotion/src/sequences/B01.tsx`, `B02.tsx`, ...
- Shorts: `remotion/src/shorts/S01.tsx`, `S02.tsx`, ...
- `remotion/src/Master.tsx` — sequences all long-form beats
- `remotion/src/MasterShort.tsx` — sequences all short-form beats (1080x1920)

**Spec integration:**
```typescript
// remotion/src/lib/spec.ts
// Reads spec JSON directly from ../../spec/ — no copy, no symlink
// Webpack/esbuild configured to allow imports outside src/
import specData from '../../spec/sequence_spec_v2.json'

export const getBeat = (id: string) => specData.beats.find(b => b.id === id)
export const PROXY_MODE = process.env.PROXY_MODE === 'true'
export const resolvePath = (assetPath: string) =>
  PROXY_MODE ? assetPath.replace('/compressed/', '/proxy/') : assetPath
```

**Parallel subagents:** Each subagent gets 1 beat (or a small group of related beats). Every subagent receives:
- Full detailed spec (all beats, not just theirs — for context)
- Full asset manifest (what's available)
- Style profile
- SKILL.md operational rules

Subagents CAN do creative work — but only when the detailed spec gives them enough specifics and per-beat validation forces them to check their output.

**Per-beat validation loop (MANDATORY, no exceptions):**

```
For each beat:
  1. WRITE B01.tsx from spec

  2. PRE-RENDER CHECKS (instant, no render needed):
     ├─ Asset grep: every asset in spec beat is imported in code
     ├─ pretext: all text elements fit within container dimensions
     │   → prepare(text, font) → layout(prepared, width, lineHeight)
     │   → if height > container: FAIL "text overflow in B01 layer X"
     ├─ No emoji: grep for emoji unicode ranges → FAIL if found
     └─ Timing: beat reads from spec JSON, not hardcoded

  3. RENDER 3 frames:
     npx remotion still --gl=angle --frame={start} → renders/validation/B01_start.png
     npx remotion still --gl=angle --frame={mid}   → renders/validation/B01_mid.png
     npx remotion still --gl=angle --frame={end}    → renders/validation/B01_end.png

  4. VISUAL CHECKS (Claude reads rendered frames):
     ├─ Layer count: spec says N layers → N distinct visual elements visible
     ├─ Asset presence: each referenced asset visible in at least one frame
     ├─ Text readable: not cut off, not overlapping other elements
     ├─ Animation evidence: start frame ≠ mid frame (something moved)
     ├─ Color match: dominant colors from spec palette present
     ├─ No blank areas: no large unexplained empty regions
     └─ OSMMap check: if beat references a location → map component used

  5. If ANY check fails:
     ├─ Identify which check failed and why
     ├─ Fix the .tsx code (update spec if fix goes beyond spec)
     ├─ Re-render, re-check
     └─ Loop until ALL pass (no attempt limit, no asking creator)

  6. PASS → log to renders/validation/B01_report.json → next beat
```

**Build rules:**

- Easing is NEVER linear. Always BEZIER, SINE, EXPO, BACK, ELASTIC, BOUNCE, or CONSTANT.
- `backdropFilter` is BANNED in Remotion — renders as kaleidoscope artifacts in headless Chrome. Use solid overlay layers with opacity.
- `<OffthreadVideo>` always, never `<Video>` — designed for non-sequential frame access.
- SVG `fill="currentColor"` resolves to BLACK in Remotion `<Img>`. Replace with actual color before using.
- `staticFile()` references `public/` — symlinks break during render. Copy actual files to `public/assets/`.
- For rotoscoping: `rembg` Python API (not CLI — broken on Python 3.14+), `u2net_human_seg` model, output as WebM VP9 alpha. See `references/remotion-compositing.md`.
- Before placing logos with rotoscope masks: extract a frame from the mask WebM to see the actual silhouette. Logos behind the person's body are invisible.
- Use `<Series>` component or dynamic offset computation for sequencing. Never hardcode timeline offsets — one change cascades everywhere.
- For karaoke subtitles: raw ASR word timestamps are the primary timing source. Never regenerate timestamps from script text. If ASR text needs correction, edit the word text while keeping ASR timestamps intact.

### Phase 7: Audio

Background music and SFX are part of the pipeline, not an afterthought. If the creator doesn't explicitly skip audio, it must be generated.

**Background music sources (in order):**
1. Creator provides a track
2. Download from YouTube Audio Library (royalty-free)
3. Lyria 2 on Vertex AI (`lyria-002`): 30s instrumental WAV at 48kHz, $0.06/clip. Stitch segments for full video. Response format varies — try `predictions[0]["generated_music"][0]["audio"]`, then `["bytesBase64Encoded"]`, then `predictions[0]["bytesBase64Encoded"]`.
4. Lyria RealTime via Gemini API: WebSocket streaming, experimental.

**HARD BAN:** Do NOT use Gemini `response_modalities=["AUDIO"]` for music. That is TTS — it produces speech narration describing music, not actual music. This has been confirmed broken.

**SFX via ElevenLabs** `text_to_sound_effects.convert()`. Env var: `ELEVENLABS_API_KEY`.

**SFX prompt rules (critical — bad prompts = garbage):**

GOOD prompts (concrete, physical, 5-10 words):
- "mechanical keyboard typing, cherry mx blue, 3 keystrokes"
- "short whoosh, fast left to right, cinematic"
- "single camera shutter click, DSLR"
- "pop notification sound, iPhone"

BAD prompts (vague, abstract, unusable):
- "dramatic mathematical reveal sound, ethereal shimmer"
- "uplifting conclusion riser, building to positive ending"
- "gentle thinking bell shimmer, moment of inspiration"

**Rule:** if you can't name a real physical object making the sound, the prompt is too abstract. Max 3-5 SFX per section. Most of the time, silence IS the transition.

**Volume hierarchy (non-negotiable):**

| Layer | Volume | Notes |
|-------|--------|-------|
| Narrator voice | 100% (boosted, punchy) | Always in front. Can duck for specific B-roll sequences. |
| SFX | 20-30% | Audible, not jarring. Punctuate, don't compete. |
| Music during silence | 10-15% | Fills gaps gently, doesn't take over |
| Music during speech | 3-5% | Felt, not heard. If you can identify the melody, it's too loud. |
| B-roll audio | 5-15% | Editorial decision per sequence. Protest crowds, news broadcasts — sometimes this IS the content. |

**Music drops to ZERO** before key statements. The silence before the punch line is more powerful than any swell.

**Audio transitions:**
- Micro-fades (80ms) at every cut boundary: `afade=type=in:duration=0.08` / `afade=type=out:duration=0.08`. Prevents audio pops.
- Unit transition fades (400-500ms) between sections.
- `amix` filter: ALWAYS use `normalize=0` and set explicit volume weights. Default divides by input count.

See `references/sfx-music-generation.md` for API details.

**Phase 7 quality gates:**

| Gate | Check |
|------|-------|
| `SFX_FILE_VALID` | Each SFX file > 10KB. ffprobe confirms valid audio codec, sample rate, duration. |
| `SFX_NOT_SILENCE` | Peak amplitude > -40dB (contains actual audio, not silence). |
| `SFX_PLACEMENT_CONCRETE` | Every `<Audio>` has concrete frame offset (not frame 0 unless intentional). |
| `SFX_CONTEXT_MATCH` | SFX type matches context — transition → whoosh, text → pop, emphasis → hit. Not random. |
| `MUSIC_NOT_SPEECH` | Generated audio is instrumental, NOT speech. Play first 10 seconds — if you hear words, the gate FAILS (wrong API: Gemini TTS instead of Lyria). |
| `MUSIC_FILE_VALID` | ffprobe confirms valid audio. File > 100KB for 30s WAV. Correct sample rate (48kHz). |
| `MUSIC_API_CORRECT` | Music generated using Lyria 2 (Vertex AI) or Lyria RealTime, or user-provided. NOT `response_modalities=["AUDIO"]`. |
| `DUCKING_WORKS` | Volume drops during speech segments (from VAD), raises during silences. |

### Phase 8: Render

**All temp files on project SSD.** Set `TMPDIR={project_root}/tmp/` in every ffmpeg and Remotion command. Never use `/tmp/` on system disk.

**Proxy → full-res swap:**
- During editing/validation (Phases 2-7): `PROXY_MODE=true` → Remotion uses `footage/proxy/` paths
- At render time: `PROXY_MODE=false` → uses `footage/compressed/` (or `footage/raw/` for camera footage)
- `lib/spec.ts` handles path resolution based on env var

**Render commands:**
```bash
# Long-form master (16:9)
cd {project}/remotion && TMPDIR=../tmp PROXY_MODE=false \
  npx remotion render src/index.ts MasterComposition \
  --output="../renders/final/video_16x9.mp4" \
  --gl=angle --codec=h264 --concurrency=50%

# Short-form (9:16)
cd {project}/remotion && TMPDIR=../tmp PROXY_MODE=false \
  npx remotion render src/index.ts MasterShort \
  --output="../renders/final/short_9x16.mp4" \
  --gl=angle --codec=h264 --concurrency=50%
```

**Master composition validation (BEFORE render):**
- `npx remotion compositions` succeeds — all compositions listed without errors
- Each beat composition renders at least 1 frame without crashing (`npx remotion still --gl=angle`)
- All media files referenced by `<OffthreadVideo>`, `<Audio>`, `<Img>` exist on disk
- No clip overlaps within a composition's video track
- SFX/overlay timing falls within the beat composition's duration
- Total Master duration = sum of beat durations + transition durations
- If ANY validation fails: **REJECT the build with explicit error listing every violation**

**Per-beat render for review (optional):**
```bash
# Render a single beat for creator review before full render
cd {project}/remotion && npx remotion render src/index.ts B01 \
  --output="../renders/drafts/B01.mp4" --gl=angle --codec=h264
```

**Interactive preview with Remotion Studio:**
```bash
cd {project}/remotion && npx remotion studio --port 3002
```
Opens at `http://localhost:3002`. Use for interactive scrubbing and visual review before final render. This is the "WATCH THIS" gate — scrub through the composition and verify it looks right.

**Render rules:**
- `--gl=angle` on EVERY `remotion render` and `remotion still` command. Default SwiftShader cannot handle MapLibre GL WebGL rendering.
- `--concurrency=50%` — don't saturate CPU, leave room for ffmpeg subprocesses.
- `<OffthreadVideo>` always, never `<Video>`.
- For videos > 5 minutes: render per-section, concatenate with ffmpeg. Avoids monolithic render timeouts. Each section is independently retryable.
- **Pre-render checks:**
  - ffprobe every media file referenced in composition — verify codec, duration, resolution
  - Check keyframe interval: if > 5s, re-encode with `-g 60` (keyframe every 2s at 30fps) to prevent stutter from seeking to wrong keyframe
  - All source videos must be seekable (no streaming formats)
- **Post-render validation:** play rendered output, spot-check against spec at 5 random timestamps.

**Layer toggling at render time:** Because subtitles, SFX, music, VFX are all separate Remotion layers (sequences), the creator can disable any layer before rendering. Want no subtitles? Comment out or prop-toggle SubtitleLayer. Want different music? Swap the MusicLayer audio source. No re-processing of anything else needed.

### Phase 9: Publish

#### Thumbnail Pipeline (MANDATORY)

Any visual output (thumbnails, title cards, reel covers, social media posts) follows this pipeline. No exceptions.

**Step 1 — Spec creation.** Every thumbnail starts with a detailed JSON spec:

```json
{
  "type": "thumbnail_16x9",
  "dimensions": [1280, 720],
  "concept": "Short description of the visual idea",
  "text": {
    "primary": "2 words max — the hook",
    "secondary": "optional subtext",
    "placement": "bottom-right on gradient bar",
    "size": "primary 100px+, readable at 120px thumbnail width"
  },
  "faces": [
    {
      "person": "Name",
      "source_photo": "exact file path",
      "cutout_quality": "verified clean / needs re-processing",
      "position": "left/center/right",
      "size": "hero (80% height) / medium (60%) / small (40%)",
      "z_index": 5,
      "treatment": "red tint / desaturated / normal",
      "expression": "serious / speaking / neutral — matters for emotion"
    }
  ],
  "background": {
    "image": "exact file path",
    "treatment": "dark grade 0.3 opacity, saturate 0.2",
    "overlay": "radial gradient / linear gradient / solid"
  },
  "graphic_elements": ["red divider line", "fire overlay", "prison bars", "giant ?"],
  "color_palette": ["primary accent", "text color", "bg tone"],
  "reference": "URL or description of the style being targeted"
}
```

**Spec validation (3 passes minimum):**

1. **Content pass:** Does every face have a concrete source photo path? Is the photo formal/appropriate (not casual NGO vest when showing a Home Minister)? Does the expression convey the right emotion?
2. **Composition pass:** Clear visual hierarchy? Faces balanced (no 5:1 size ratios)? No dead space? Eye travels face → text → back? Faces overlapping for depth or floating in isolation?
3. **Readability pass:** At 120px wide (YouTube mobile), can you read the text? Text on contrasting background (gradient bar, solid color, not just shadow)? Text avoids platform overlay zones (bottom 15% for timestamp, top-right for duration badge)?

Codex/agent review required after the 3 passes.

**Step 2 — Generate with Gemini (primary method):**

```python
from google import genai
from google.genai import types
from PIL import Image

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
photos = [Image.open(path) for path in photo_paths]

response = client.models.generate_content(
    model="gemini-3.1-flash-image-preview",
    contents=[
        photo1, "This is [Name] �� put them [position], [size], [treatment].",
        photo2, "This is [Name] — put them [position].",
        "Generate a YouTube thumbnail (16:9): [detailed visual spec from Step 1]"
    ],
    config=types.GenerateContentConfig(
        response_modalities=['TEXT', 'IMAGE'],
    ),
)

for part in response.parts:
    if part.inline_data is not None:
        part.as_image().save("thumbnail.png")
```

Rules: feed ACTUAL photos (Gemini uses real faces), be explicit about position/size/overlap/treatment, say "Use EXACTLY these faces" to prevent substitution. Generate multiple variations, validate each before showing creator.

**Step 3 — Iteration (3 rounds minimum):**

1. **Iteration 1:** Render, check cutout quality (no artifacts?), text readability, composition balance.
2. **Iteration 2:** Compare against reference style. Does it look DESIGNED or ASSEMBLED? Faces overlapping with depth? Graphic elements adding drama?
3. **Iteration 3:** Shrink to 120px wide. Can you read the text? Identify the faces? Is the emotional hook clear? If not, simplify.

**Validation gate (must pass before showing creator):**
- [ ] All cutouts artifact-free (no rectangles, no fringe, no other people)
- [ ] Text readable at 120px width
- [ ] No face cropped at chin/forehead unintentionally
- [ ] Visual hierarchy clear (eye knows where to go)
- [ ] Looks designed, not assembled
- [ ] At least one emotional/dramatic element (expression, color, symbol)

**Anti-patterns:**
- Don't show 5 variations after 1 render — iterate each one 3 times before presenting
- Don't use casual/wrong photos — a Home Minister should look like a Home Minister
- Don't leave dead space — fill with a face or graphic element
- Don't put text where YouTube overlays cover it (bottom-right timestamp, top-right duration badge)
- Don't skip cutout validation — one rectangular artifact destroys the professional look

#### YouTube Metadata

- Title, description with chapters, tags, category
- Language from `project.language`: `ne` or `ne+en` → `"ne"`, `en` → `"en"`
- Shorts metadata separately
- Creator approves before upload

See `references/youtube-metadata-spec.md`.

## 9:16 Shorts Rules

Shorts are NOT crops of 16:9. They are full recompositions at 1080x1920.

**Structural rules:**
- First 10 seconds is the make-or-break. Best effort on animation, delivery, problem statement.
- Last 5 seconds: teaser for full video. Thumbnail of the full video + follow CTA.
- Karaoke-style subtitles: bottom-third, word-by-word highlight as spoken. Large font (56-64px), semi-transparent pill backdrop.
- Own narration script (`spec/shorts/narration_shorts.txt`), own spec, own Remotion compositions.
- Shared assets with long-form (same `assets/` pool).
- Can be built in parallel with long-form.

**Recomposition rules (when using 16:9 source footage in 9:16):**
- Talking head: crop to face+shoulders, bias toward top
- Screen recording: scale to fit width, blurred BG fill. Content must be fully readable.
- Animation (16:9 designed): scale to fit, add context above/below. Never crop a diagram.
- New captions designed for 1080px width with safe margins.

See `EXTRA_SKILL.md` for advanced recomposition with YOLO-driven dynamic cropping.

## Screen Recording Sync

When the creator provides both camera footage and screen recordings of the same session:
```bash
python3 scripts/sync_screen_recording.py <project_root>
```
Audio cross-correlation finds the sync offset. Ask creator to choose layout (PiP, split, switch, side-by-side). See `references/screen-recording-sync.md`.

## Agent Protocol

**Subagents do creative work ONLY when given a detailed spec with validation criteria.** No subagent operates from vague instructions.

When spawning parallel agents:

1. **Never downgrade creator instructions.** Pass verbatim if possible otherwise upgrade what is needed. If a task seems too hard, it is because it doesn't have enough information. if you can do it yourself add yourself other wise ask. The main agent does not pre-decide what's feasible.

2. **Every subagent gets full context:**
   - Full detailed spec (all beats, not just theirs)
   - Full asset manifest
   - Style profile
   - SKILL.md rules
   - What every other subagent is working on

3. **Mutations scoped to assigned beat only.** A subagent working on B12 does not modify B11 or B13.

4. **Never spawn two agents that write to the same file.**

5. **Inter-beat work stays with main agent:** transitions between beats, global music layer, narrative reordering.

6. **Include relevant reference docs** in spawn prompt. Each phase has specific docs agents need.

**Agent anti-pattern catalog (observed in real runs — watch for these):**

| Anti-pattern | What happens | How to detect |
|-------------|-------------|---------------|
| **Scope reduction** | Creator asks for 5 things, agent does 2 and presents as complete | Count creator requirements vs pass conditions checked. If fewer conditions than requirements, scope was reduced. |
| **Complexity collapse** | Task needs 6 steps, agent produces a 1-step approximation ("too complex") | Plan must have at least as many steps as the task requires. Fewer steps = collapsing complexity. |
| **Silent substitution** | Creator says "rotoscope", agent produces CSS glow and never reports failure | Research step must understand what terms actually mean. If agent can't do what the term requires, report failure — don't substitute. |
| **First-obstacle bailout** | rembg fails on one frame → agent abandons entire task | Every sub-step must have a fallback. A single error does not justify abandoning the whole task. Try alternatives before declaring failure. |

**Agent failure protocol:**
- Do NOT produce garbage. Empty result > wrong result.
- Do NOT silently substitute easier approaches. If the spec says rotoscope, you rotoscope or you report failure.
- Write failure details to the validation report: what was attempted, what failed, what alternatives exist.
- Auto-fix and retry. Only escalate to creator when genuinely stuck after exhausting alternatives.

## Dependency Notes

**DeepFilterNet:** Use `deep-filter` Rust CLI ONLY (v0.5.6, aarch64-apple-darwin for Apple Silicon). The `deepfilternet` pip package is broken — pulls numpy 1.x, conflicts with cv2/ultralytics. Never install it.

**torch ecosystem:** Always upgrade together: `torch + torchaudio + torchvision + torchcodec`. `silero-vad` can trigger version drift.

**numpy ≥ 2.0:** Required by cv2, ultralytics. The deepfilternet pip package pulls 1.26.4 — another reason to never install it.

**pretext:** Added to Remotion project `package.json`. Used in pre-render validation to measure text layout without DOM. `prepare(text, font) → layout(prepared, width, lineHeight) → {height, lineCount}`.

## Directory Structure

```
{project_name}/
├── spec/
│   ├── rough_spec_v1.md              # Level 1 — creator reads (~300 lines)
│   ├── sequence_spec_v1.json         # Level 2 — detailed, speculative timing
│   ├── sequence_spec_v2.json         # After narration remap
│   ├── narration_text.txt            # Long-form teleprompter
│   ├── shorts/
│   │   ├── rough_spec_v1.md
│   │   ├── sequence_spec_v1.json
│   │   └── narration_shorts.txt
│   └── changelog.md
│
├── research/
│   ├── checklist.json
│   ├── brief.md
│   ├── transcripts/
│   └── sources/
│
├── assets/
│   ├── asset_list.json               # From research (exhaustive)
│   ├── manifest.json                 # Status registry (ready/failed/needs_review)
│   ├── people/
│   ├── flags/
│   ├── clips/
│   ├── icons/
│   ├── textures/
│   └── sources/
│
├── footage/
│   ├── raw/                          # Originals (never modified)
│   ├── proxy/                        # 720p for editing
│   ├── denoised/                     # Audio-denoised
│   └── compressed/                   # OBS re-encodes
│
├── analysis/
│   ├── transcripts/                  # ASR output
│   ├── retake_report.json
│   ├── clean_pass_report.json
│   └── vad/
│
├── remotion/
│   ├── package.json                  # Includes pretext, @remotion/cli, react, etc.
│   ├── remotion.config.ts
│   ├── src/
│   │   ├── index.ts                  # Registers all compositions
│   │   ├── Root.tsx
│   │   ├── Master.tsx                # Long-form master
│   │   ├── MasterShort.tsx           # Short-form master (1080x1920)
│   │   ├── components/               # Shared (VideoClip, SubtitleRenderer, AudioLayer, OSMMap, etc.)
│   │   ├── sequences/                # Per-beat: B01.tsx, B02.tsx, ...
│   │   ├── shorts/                   # Per-beat: S01.tsx, S02.tsx, ...
│   │   └── lib/
│   │       ├── spec.ts               # Reads spec JSON, getBeat(), path resolution, PROXY_MODE
│   │       ├── types.ts
│   │       └── utils.ts
│   └── public/
│       └── assets/                   # Copies from ../../assets/
│
├── audio/
│   ├── music/
│   ├── sfx/
│   └── narration/
│
├── renders/
│   ├── validation/                   # Per-beat still frames + reports
│   ├── drafts/
│   └── final/
│
├── tmp/                              # ON PROJECT SSD, never /tmp
├── thumbnails/
└── footage_manifest.json             # Media inventory (ffprobe data, file paths)
```

## Reference Docs

Read from `references/` when the phase requires it:

| Doc | When to read |
|-----|-------------|
| `asr-chirp-setup.md` | Phase 4, Phase 5 — ASR configuration |
| `sfx-music-generation.md` | Phase 7 — ElevenLabs SFX + Lyria music APIs |
| `remotion-compositing.md` | Phase 6 — rotoscoping, FullVideo pattern, VP9 alpha |
| `transition-fundamentals.md` | Phase 6 — MANDATORY before writing any transition code |
| `source-citation-style.md` | Phase 1, Phase 6 — visual source citations |
| `social-media-download.md` | Phase 1, Phase 3 — platform download matrix, Facebook/TikTok |
| `source-screenshot-pipeline.md` | Phase 1, Phase 3 — Playwright capture |
| `animation-style-config.md` | Phase 6 — style consistency for animations |
| `crop-easing-guide.md` | Phase 6 — 9:16 crop strategies + easing |
| `ken-burns-style-guide.md` | Phase 6 — Ken Burns patterns |
| `screen-recording-sync.md` | Phase 5 — audio cross-correlation sync |
| `youtube-metadata-spec.md` | Phase 9 — YouTube upload metadata |
| `manifest-schema.md` | Any phase — footage_manifest.json schema |

## Creator Approval Gates

These phases MUST pause and wait for creator input. Do not proceed without approval:

| Phase | What needs approval |
|-------|-------------------|
| Phase 1 | Narration scripts (long-form + shorts) + both rough specs |
| Phase 3 | Asset manifest before fetching (creator can add/remove). Asset dashboard after fetching (creator resolves needs_review items). |
| Phase 5 | Retake report (before any cutting). Clean footage pass report (before cutting). |
| Phase 7 | SFX placement plan (dry-run before generation). Music style. |
| Phase 8 | Creator scrubs Remotion Studio preview before final render. |
| Phase 9 | Thumbnail selection. YouTube metadata. |

## Error Recovery

The `footage_manifest.json` tracks `pipeline_state.completed_phases`. If the pipeline fails:
1. Read the manifest to find the last completed phase
2. Resume from the next phase
3. Individual beats can be re-processed without affecting others
4. The spec is the recovery anchor — as long as the spec is intact, any phase can be re-run

## Phase 10: Cleanup

After final render is approved:
- Remove `tmp/` directory
- Remove `renders/validation/` (per-beat stills no longer needed)
- Remove `footage/proxy/` (proxies no longer needed after render)
- Optionally remove `analysis/` (data is captured in footage_manifest.json)
- **Always preserve:** `footage/raw/`, `footage/compressed/`, `renders/final/`, `spec/`, `assets/`, `footage_manifest.json`, `remotion/`

## What NOT To Do

- Do NOT use `deepfilternet` pip package — use `deep-filter` Rust binary
- Do NOT use Gemini `response_modalities=["AUDIO"]` for music — that is TTS
- Do NOT use `auto` language detection with Chirp 2 — misidentifies Nepali
- Do NOT use linear easing for anything
- Do NOT use `backdropFilter` in Remotion — kaleidoscope artifacts in headless Chrome
- Do NOT use `<Video>` in Remotion — use `<OffthreadVideo>` always
- Do NOT hardcode timeline offsets — use `<Series>` or dynamic computation
- Do NOT modify Remotion code without updating the spec first
- Do NOT skip per-beat validation — render frames and READ them
- Do NOT use emoji in any visual element — SVG or CSS-drawn only
- Do NOT use /tmp on system disk — use `{project_root}/tmp/` on SSD
- Do NOT render without `--gl=angle` — MapLibre GL needs it
- Do NOT trust ASR alone for retake detection on clips > 60s
- Do NOT generate SFX from abstract prompts — name a real physical sound source
- Do NOT set background music above 5% during speech — it must be felt, not heard
- Do NOT crop 16:9 to 9:16 — recompose from scratch
- Do NOT let subagents operate from vague instructions — detailed spec required
- Do NOT ask the creator to read the detailed spec — they read rough spec only
- Do NOT regenerate subtitle timestamps from script text — keep ASR timestamps, edit word text only
