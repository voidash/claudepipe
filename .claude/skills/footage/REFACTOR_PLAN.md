# Footage Skill Refactor — Final Architecture

All decisions finalized. This doc is the blueprint for the new SKILL.md.

---

## Core Philosophy (goes at very top of SKILL.md)

1. **NARRATION DRIVES THE VIDEO.** ASR word timestamps are the real timeline. Composition spec timing is speculative until narration exists. When narration arrives, everything remaps.
2. **THIS IS VIDEO CREATION, NOT SOFTWARE ENGINEERING.** Code that compiles ≠ good video. Every write must be validated visually (render frame → read it → check against spec). 
3. **SPEC IS THE SINGLE SOURCE OF TRUTH.** Any code change → update spec first → then code. Never the reverse. Spec has two levels: rough (human-readable, ~300 lines) and detailed (Claude/Codex territory, 5000+ lines).
4. **VALIDATE AFTER EVERY WRITE.** No batching validation to the end. Per-beat render-read-check loop. Auto-fix, keep trying, no attempt limit.
5. **SLOW IS FINE IF CORRECT.** Parallel subagents per sequence, not batched shortcuts. A 4-hour correct build beats a 1-hour broken build.

---

## What Gets Killed

- Studio web app as editor (stays as viewer/player only)
- edit_manifest.json and the entire PATCH API system
- Server-authoritative editing, Express routes for mutations
- NLE operations in studio (trim/split/drag/delete as UI operations)
- The "unit" concept (replaced by "beat" / "sequence")
- Phase 12 studio interactive session as a pipeline phase
- All 20-phase numbering (replaced by new 9-phase pipeline)

## What Gets Merged

- USER-SKILL.md operational findings → into relevant sections of new SKILL.md + reference docs
- USER-SKILL.md deleted after merge

## What Gets Added

- Two-level spec system (rough + detailed)
- Research phase with 3 deliverables + checklist
- Retake detection protocol (multi-pass, cross-clip)
- Clean footage pass
- Per-beat validation loop with pretext
- Proxy workflow
- OBS compression on ingest
- Codex/agent spec review protocol
- pretext as Remotion dependency

---

## New Pipeline (9 phases)

### Phase 1: Research
- Inputs: topic, user material, /last30days, web search
- Three deliverables:
  1. `research/narration_text.txt` — clean teleprompter, no markers, just paragraphs
  2. `assets/asset_list.json` — exhaustive (1000+ ok), per-asset: id, type, query, context, needed_for beats, source_hints, priority, status
  3. `spec/rough_spec_v1.md` — ~300 lines, human-readable, section-level (what happens, key assets, mood). User reads and approves this.
- `research/checklist.json` tracks every research task with tick/notes

### Phase 2: Composition Spec
- Inputs: approved rough spec + narration text + asset list
- Claude expands rough spec → detailed `spec/sequence_spec_v1.json`
  - Per-beat: id, name, time (speculative), dur, layers (natural language with full specifics — colors, sizes, pivots, easing, animation, validation criteria), assets, transitions
  - Custom visuals get sub-specs within the layer description (SVG elements, animation behavior, positioning, what to validate)
  - `timing_source: "speculative"` until narration maps
  - Rules block at top (min layers, asset requirements, no-emoji, etc.)
- Review loop: Claude drafts → Codex/agent reviews → Claude revises → repeat until reviewer passes
- User NEVER reads the detailed spec. User only approved rough spec in Phase 1.
- Spec versioning: v1 (speculative) → v2 (narration-mapped) → v3+ (changes)
- `spec/changelog.md` tracks what changed and why

### Phase 3: Asset Acquisition
- Inputs: asset_list.json + spec asset references
- Parallel download agents
- Validation per asset:
  - Photos: Claude reads downloaded image, checks identity/quality
  - Videos: download → extract transcript → LLM check "does this show what we need?" 
  - Videos from Facebook first (Nepal content arrives there before YouTube)
  - Generated assets (flags, textures, grain): generate, never fetch
- Per-asset checklist in `assets/manifest.json` — every asset ends as ready/failed/needs_review
- Asset count is sacred: all must be accounted for

### Phase 4: Narration
- Option A: user records → provides footage files
- Option B: edge-tts placeholder → dummy image for camera slot
- In BOTH cases: ASR (Chirp 2) on narration audio → word-level timestamps
- Chirp 2 rules:
  - Max 60s sync. Chunk at 50s with 5s overlap.
  - Single language code only (ne-NP or en-US). Never auto-detect.
  - us-central1, europe-west4, or asia-southeast1 only.
  - After chunk merge: verify transcribed coverage ≥ 80% of duration
- Spec remap: word timestamps → beat timings. `timing_source` flips to `"narration"`
- Output: `spec/sequence_spec_v2.json`

### Phase 5: Footage Processing (when user provides camera footage)
- OBS compression on ingest: HEVC high-bitrate → H.264 CRF 23 (visually identical, ~90% smaller)
- Proxy generation: 720p H.264 CRF 28 for editing/validation
- Denoise: deep-filter Rust CLI on extracted audio → mux back
- ASR on all clips (same Chirp 2 rules as Phase 4)
- **Retake detection (multi-pass):**
  1. Text search: "retake", "रिटेक", "sorry", frustration markers
  2. Repeated content: LLM comparison across transcript segments (similarity > 0.7 = retake)
  3. Cross-clip stitching: clip N tail + clip N+1 head compared for content overlap
  4. Audio patterns: long silence (>3s) + speech restart = likely retake boundary
  5. Gemini Flash video scan if inconclusive
- **Retake report** presented to user: which clips, what to keep, what to cut, stitch plan
- User approves cuts → `analysis/retake_report.json`
- **Clean footage pass:**
  - Dead silence > 3s: flag
  - Low ASR confidence < 0.5: flag (mumbling)
  - Audio clipping/distortion: flag
  - Repeated false starts within 5s: flag
  - Output: `analysis/clean_pass_report.json` — user reviews
- Spec remaps AGAIN to real footage timing → `spec/sequence_spec_v3.json`

### Phase 6: Build
- Generate per-beat Remotion .tsx files FROM the detailed spec
- Each beat = one file: `remotion/src/sequences/B01.tsx`, `B02.tsx`, ...
- Code reads timing from spec JSON directly (via lib/spec.ts utility)
- Timing changes in spec → no code changes needed
- **Parallel subagents**: each subagent gets 1 beat (or a small group), full spec context
- **Per-beat validation loop (mandatory, no exceptions):**
  1. Pre-render checks: asset grep, pretext text measurement, no emoji grep, timing from spec
  2. Render 3 frames: start, mid, end → `renders/validation/B01_{start,mid,end}.png`
  3. Visual checks (Claude reads frames): layer count, asset presence, text readability, animation evidence, color match, no blank areas
  4. If ANY check fails → auto-fix → re-render → re-check → loop until all pass
  5. Pass → log to `renders/validation/B01_report.json`
- Master.tsx: sequences all beats via <Series.Sequence>
- `remotion/src/lib/spec.ts`: reads `../../spec/sequence_spec_v{N}.json` directly (no copy/symlink)

### Phase 7: Audio
- Background music: Lyria 2 (Vertex AI) or user-provided or downloaded
- SFX: ElevenLabs text_to_sound_effects — concrete prompts only, no abstract vibes
- Volume hierarchy (non-negotiable):
  1. Narrator voice — 100% (boosted, punchy, in front)
  2. SFX — 20-30%
  3. Music during silence — 10-15%
  4. Music during speech — 3-5% (felt, not heard)
- Music drops to ZERO before key statements
- Micro-fades (80ms) at every cut boundary
- Unit transition fades (400-500ms)

### Phase 8: Render
- All tmp on SSD: `TMPDIR={project_root}/tmp/`
- Proxy → full-res swap: `PROXY_MODE` flag in lib/spec.ts
- `<OffthreadVideo>` always (not `<Video>`)
- `--gl=angle` on every render/still
- `--concurrency=50%`
- For videos > 5min: render per-section, concatenate with ffmpeg
- Pre-render: ffprobe every referenced media file
- Keyframe check: if interval > 5s, re-encode with `-g 60`
- Validate rendered output against spec

### Phase 9: Publish
- Thumbnails (Gemini nanobanana or Remotion Still)
- YouTube metadata (title, description, chapters, tags)
- User approves

---

## Directory Structure

```
{project_name}/
├── spec/
│   ├── rough_spec_v1.md              # Level 1 — user reads (~300 lines)
│   ├── sequence_spec_v1.json         # Level 2 — Claude/Codex (detailed, speculative timing)
│   ├── sequence_spec_v2.json         # After narration remap
│   ├── narration_text.txt            # Clean teleprompter
│   └── changelog.md                  # Version history
│
├── research/
│   ├── checklist.json                # Ticked research tasks
│   ├── brief.md                      # Research synthesis
│   ├── transcripts/                  # YouTube/source transcripts
│   └── sources/                      # Citation screenshots, QR codes
│
├── assets/
│   ├── asset_list.json               # Exhaustive asset list from research
│   ├── manifest.json                 # Asset registry (status per asset)
│   ├── people/
│   ├── flags/
│   ├── clips/
│   ├── icons/
│   ├── textures/
│   └── sources/
│
├── footage/
│   ├── raw/                          # Original files
│   ├── proxy/                        # 720p proxies
│   ├── denoised/                     # Audio-denoised
│   └── compressed/                   # OBS re-encodes
│
├── analysis/
│   ├── transcripts/                  # ASR output
│   ├── retake_report.json            # Detected retakes + approved cuts
│   ├── clean_pass_report.json        # Silence/mumble/artifact report
│   ├── vad/
│   └── scenes/
│
├── remotion/
│   ├── package.json                  # Includes pretext dependency
│   ├── remotion.config.ts
│   ├── src/
│   │   ├── index.ts                  # Registers all compositions
│   │   ├── Root.tsx
│   │   ├── Master.tsx                # Sequences all beats
│   │   ├── components/               # Shared (VideoClip, SubtitleRenderer, AudioLayer, etc.)
│   │   ├── sequences/                # Per-beat: B01.tsx, B02.tsx, ... B83.tsx
│   │   └── lib/
│   │       ├── spec.ts               # Reads spec JSON, provides getBeat(), timing resolution
│   │       ├── types.ts
│   │       └── utils.ts
│   └── public/
│       └── assets/                   # Symlinks to ../../assets/
│
├── audio/
│   ├── music/
│   ├── sfx/
│   └── narration/                    # Recorded narration + ASR JSON
│
├── renders/
│   ├── validation/                   # Per-beat still frames + reports
│   ├── drafts/
│   └── final/
│
├── tmp/                              # ON SSD, never /tmp
├── thumbnails/
└── footage_manifest.json             # Media inventory (ffprobe, file paths, ASR refs)
```

---

## Key Technical Decisions

1. **Spec JSON imported directly by Remotion code** — via lib/spec.ts, webpack config allows imports outside src/. No copy, no symlink.
2. **83 files for 83 beats** — one .tsx per beat. Subagents work on isolated files, less context to read.
3. **pretext in Remotion deps** — used in pre-render validation to check text layout without rendering.
4. **Proxy mode** — `PROXY_MODE` env var. lib/spec.ts resolves media paths to proxy/ or compressed/ accordingly.
5. **OBS compression on ingest** — HEVC 70Mbps → H.264 CRF 23. Run once when footage enters project.
6. **Retake detection is multi-pass** — text search, content comparison, audio patterns, optional Gemini scan. User approves before cuts.
7. **Studio is viewer only** — Express serves media and hosts player. No editing mutations.
8. **Codex/agent review** — invoked via codex-cli. Prompt must include: narration text, asset list, specific checks, open-ended questions. Not just "review this."
9. **Auto-fix on validation failure** — no attempt limit, no "ask user", just keep fixing until it passes.
10. **All tmp on project SSD** — TMPDIR set explicitly in every ffmpeg and Remotion command.

---

## Reference Docs Audit (which to keep)

KEEP (still relevant):
- manifest-schema.md — needs update for new structure but concept stays
- asr-chirp-setup.md — Chirp 2 setup unchanged
- sfx-music-generation.md — ElevenLabs + Lyria docs
- remotion-compositing.md — rotoscoping, FullVideo pattern
- transition-fundamentals.md — AE transition rules
- source-citation-style.md — visual citations
- social-media-download.md — platform download matrix
- source-screenshot-pipeline.md — Playwright capture
- animation-style-config.md — style consistency
- crop-easing-guide.md — 9:16 crop + easing
- ken-burns-style-guide.md — Ken Burns patterns

KILL or MERGE:
- pipeline-runtime-notes.md — merge into SKILL.md operational rules
- studio-instruction-protocol.md — studio editing is dead, kill
- vfx-pipeline-plan.md — merge into Phase 6 build section
- short-form-workflow.md — review if still relevant, likely merge
- screen-recording-sync.md — review if still relevant
- gemini-video-understanding.md — keep if Gemini video scan stays
- youtube-metadata-spec.md — keep for Phase 9
- music-generation-sonauto.md — review if sonauto is still used
- creator-style-research.md — merge into Phase 0 / style system
- clip-acquisition-pipeline.md — merge into Phase 3
- youtube-clip-scout-pipeline.md — merge into Phase 3

NEW:
- composition-spec-format.md — formal spec schema + examples
- validation-protocol.md — per-beat validation loop details
- retake-detection.md — full retake protocol
- proxy-workflow.md — proxy/full-res swap + OBS compression
