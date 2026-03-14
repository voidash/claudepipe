# Footage Pipeline — Evolving Operational Knowledge

This file captures operational findings, workarounds, and lessons learned from running the pipeline on real footage. **SKILL.md is the ground truth spec. This file is the living supplement that evolves with each pipeline run.**

Update this file when you discover new gotchas, confirm or invalidate assumptions, or find better approaches.

---

## Architecture Principles (2026-03-14)

### Global Timeline with Unit Groups
- One global multi-track timeline, units are logical views into it
- Each unit = one concept/topic, NOT one clip
- Five takes of the same intro → one unit with best take selected, rest deselected with reasons
- Long clip covering two topics → split into two units at topic boundary

### Parallel Agent Attention
- Every parallel agent gets FULL global context (all units, all instructions, all agent assignments)
- Agents only WRITE to their assigned unit
- Inter-unit work (transitions between units, music, narrative order) stays with main agent
- This is like attention: each agent attends to everything but only produces output for its position

### Agent Quality Problem (why gates exist)
- Parallel agents take the path of least resistance when uncertain
- Music agent used Gemini TTS instead of Lyria → produced speech narration, reported success
- SFX agent generated sounds without understanding context → random sounds at random times
- Root cause: no accountability, no verification, no failure protocol
- Fix: dry-run plan → execute → quality gates → fail loudly if gates don't pass

### Trim Enforcement
- User-set trims are sacred — enforced by exporter AND Phase 18 validation
- Non-destructive: original range preserved, trim range is what exporters use
- deleted_ranges: gaps within trim that exporter skips
- Enforcement is in the deterministic export script, NOT in Claude's hands

### NLE Operations in Studio
- Trim, split, drag-between-units, delete-chunk — all data mutations on edit_manifest
- Source files never touched
- Versioning via git auto-commit on each sync

---

## Vision Analysis (Phase 9)

### Gemini Flash backend
- Default backend (`style_config.json → pipeline.vision_backend`)
- ~$0.03/8min video at low resolution — cheapest option
- Joint audio+visual understanding gives richer descriptions than frame-by-frame
- 1-second timestamp granularity only — not frame-accurate
- Nepali audio understanding unconfirmed — do NOT use as ASR replacement
- Gemini `scene_boundaries[]` output supplements but does not replace OpenCV Phase 6

### Claude Vision backend
- Fallback when `google.genai` not configured
- Consumes context window tokens — limit to ~10 frames per clip
- No audio context, no temporal continuity

---

## Music Generation (Phase 15)

### What works
- **Lyria 2 on Vertex AI** (`lyria-002`): GA, $0.06/30s clip, 48kHz WAV, instrumental only
  - Response format varies: try `predictions[0]["generated_music"][0]["audio"]`, then `["bytesBase64Encoded"]`, then `predictions[0]["bytesBase64Encoded"]`
  - Prompts must be US English
  - 10-20s latency per generation
- **Lyria RealTime** (`models/lyria-realtime-exp`): WebSocket streaming via Gemini API, PCM16 48kHz stereo
  - Good for longer continuous tracks without stitching
  - Experimental (`v1alpha`)
- **User-provided tracks**: Always works. Pipeline computes ducking keyframes.

### What does NOT work
- **Gemini `response_modalities=["AUDIO"]`**: This is TTS (text-to-speech). Produces speech narration describing music, not actual instrumental tracks. Confirmed broken for music 2026-03-13.
- **Suno/Udio**: No official public APIs. Third-party wrappers are legally gray.

---

## SFX Generation (Phase 14)

- ElevenLabs `text_to_sound_effects.convert()` works well for whooshes, blips, transitions
- Generated files are small (16-28KB MP3s) — always verify not silence
- Env var: `ELEVENLABS_API_KEY` (not `ELEVEN_API_KEY`)
- SFX placement data MUST include concrete `after_segment` references — null values break FCPXML positioning
- Transition SFX go at unit boundaries; within-unit SFX need `time_offset_seconds` from segment start

---

## FCPXML Export (Phase 17)

### DaVinci Resolve bugs (confirmed)
- **Volume keyframes ignored on import** — longstanding bug. Write them for FCP; store in manifest for manual DaVinci application
- **Audio transitions ignored** on import
- **Audio roles metadata dropped** — collapses to single track
- **Connected clip audio** may not roundtrip correctly

### Frame boundary rule
ALL time values (`offset`, `start`, `duration`) MUST be exact multiples of `frameDuration`. For 29.97fps: `N*1001/30000s`. Violating this → "not on edit frame boundary" error.

### GoPro timecodes
GoPro embeds clock timecodes in `tmcd` stream. DaVinci uses these as clip addresses. Fix: remux to strip `tmcd` before export:
```
ffmpeg -i in.mp4 -map 0:v:0 -map 0:a:0 -c copy -write_tmcd 0 out.mp4
```
Then use `start="0/1s"` in FCPXML.

### Media consolidation
DaVinci clip search is NOT recursive. All media must be flat in `exports/media/`.

### Connected clips (SFX)
- `lane="1"` = above primary storyline, `lane="-1"` = below
- `offset` is relative to **parent spine timeline**, not parent clip
- `<adjust-volume>` lives on `<audio>` element, not `<asset-clip>`
- Keyframe values are linear gain (0.0-1.0), not dB

---

## ASR / Chirp 2 (Phase 4)

- Chirp 2 only in: `us-central1`, `europe-west4`, `asia-southeast1`
- Multi-language codes (`["ne-NP", "en-US"]`) require `eu`/`global`/`us` locations — mutually exclusive with Chirp 2
- Always use single `["ne-NP"]` — Chirp 2 handles English code-switching adequately
- Auto-detect (`["auto"]`) misidentified Nepali as Latin (confidence 0.62) — never use
- Sync Recognize: 60s max. Split >55s clips into 52s chunks with 3s overlap

---

## Dependency Chain

### torch ecosystem
```
torch 2.10.0 + torchaudio 2.10.0 + torchvision 0.25.0 + torchcodec 0.10.0
```
Always upgrade all four together. `silero-vad` v6.2.1 pulls torchaudio which can upgrade torch.

### numpy ≥ 2.0
cv2, manim, ultralytics all need numpy ≥ 2.0. The `deepfilternet` pip package pulls numpy 1.26.4 — **never install it**.

### DeepFilterNet
Use Rust binary `deep-filter` v0.5.6 only. macOS arm64: `deep-filter-0.5.6-aarch64-apple-darwin`. Expects 48kHz input.

---

## Phase-Specific Manifest Keys

| Phase | Reads | Writes |
|---|---|---|
| 3 (Audio) | `clip.symlink_path` | `clip.audio.{extracted_path, denoised_path, duration_seconds}` |
| 4 (ASR) | `clip.audio.duration_seconds` | `clip.transcript.{path, engine, word_count, segments}` |
| 5 (VAD/Pitch) | `clip.audio.{denoised_path, extracted_path}` | `clip.vad`, `clip.pitch` |
| 6 (Scenes) | `clip.symlink_path` or raw/ | `clip.scenes.boundaries[]` |
| 7 (Frames) | `clip.vad`, `clip.pitch`, `clip.scenes` | `clip.frames.{path, count, extracted[]}` |
| 8 (YOLO) | `clip.frames.extracted[].path` | `clip.yolo` |
| 9 (Vision) | Gemini: `clip.symlink_path`. Claude: `clip.frames.extracted[].path` | `clip.vision.{backend, segments[], scene_boundaries[], per_frame[]}` |

**Key naming matters:** Phase 8 reads `clip.frames.extracted[].path` — if you use a different key (e.g., `frame_list`), YOLO silently skips all frames.

---

## Merge Contract (Phase 16b → Phase 17)

FCPXML export expects this exact structure from merge:
- Each segment: `id` (e.g., `seg_000_clip_2461`), `in_point`, `out_point`
- `timeline.order`: list of segment IDs (not `unit_order`)
- Transitions: `from_segment`/`to_segment` (not `from_unit`/`to_unit`)
- All referenced clips in main `clips[]` array (including animations, inserted media)

---

## Remotion Full-Video Compositing (Phase 13)

### Rotoscoping with rembg
- Use Python API (`from rembg import remove`), NOT the CLI entry point (broken on Python 3.14+)
- `u2net_human_seg` model: ~0.5s/frame, good for people, indoor
- Output as WebM VP9 alpha: `ffmpeg -c:v libvpx-vp9 -pix_fmt yuva420p -crf 20 -b:v 0`
- ~3MB WebM for 4s of 1920x1080 — far better than PNG sequences (~240MB)
- Use `<OffthreadVideo transparent>` in Remotion to respect alpha channel

### Logo positioning with rotoscope
- **Critical mistake to avoid**: logos placed directly behind the person's body are INVISIBLE (occluded by the rotoscope mask)
- ALWAYS extract a frame from the rotoscope WebM first to see the actual silhouette:
  ```
  ffmpeg -i person_rotoscope.webm -vf "select=eq(n\,50)" -frames:v 1 -update 1 mask_check.png
  ```
- Position logos at frame edges where background is visible (corners, gaps between arms/body)
- Use explicit target coordinates, not angle-based circle placement — much easier to control

### SVG logo gotcha
- `fill="currentColor"` in SVGs resolves to BLACK when loaded via Remotion's `<Img>` component
- Must replace with actual brand color (e.g., `fill="#D97706"`) before using
- CSS filter color transitions (`sepia() hue-rotate() saturate() brightness()`) work on all image formats — operates on rendered pixels

### Content-aware VFX
- Extract thumbnails at 5s intervals to understand what's happening in the footage
- Map content segments to frame ranges (intro talking, screen recording, rendered output, etc.)
- Assign appropriate effects per segment type — don't just random effects everywhere
- One VFXOverlay component with frame-range-gated sub-effects is cleaner than multiple Sequences

### Verification workflow
- ALWAYS render still frames before presenting anything visual to the user:
  ```
  npx remotion still src/index.ts FullVideo out/check.png --frame=50
  ```
- Check multiple frames across different effects (not just frame 0)
- `npx remotion studio` for interactive preview, but stills are the ground truth for what renders look like

### Source files in public/
- `staticFile()` references `public/` directory
- Remotion copies `public/` to temp bundle dir during render — **symlinks break**
- Must copy actual files into `public/`, not symlink

---

## Background Agent Quality Gates

Background agents for SFX/music generation MUST:
- ffprobe all generated files (confirm format, duration, codec)
- Verify file sizes are reasonable (>10KB for SFX, >100KB for 30s music WAV)
- Play-test or spot-check audio quality
- Report failures explicitly — do not silently skip
