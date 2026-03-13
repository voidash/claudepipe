# Pipeline Runtime Notes

Operational findings from running the footage pipeline on real footage. This is NOT the pipeline spec (that's SKILL.md) — this is what actually happens when you run it, the gotchas, workarounds, and format expectations between phases.

## Dependency Chain

### torch ecosystem must stay in sync
```
torch 2.10.0 + torchaudio 2.10.0 + torchvision 0.25.0 + torchcodec 0.10.0
```
- `silero-vad` v6.2.1 pulls torchaudio which can upgrade torch
- If torch upgrades, torchvision breaks (pinned to specific torch versions)
- torchaudio ≥ 2.10 needs `torchcodec` for audio I/O
- Fix: always upgrade all four together

### numpy must stay ≥ 2.0
- cv2, manim, ultralytics all need numpy ≥ 2.0
- The `deepfilternet` pip package pulls numpy 1.26.4 → **never install it** (use Rust binary `deep-filter` instead)

### DeepFilterNet
- Use pre-compiled Rust binary `deep-filter` v0.5.6 from GitHub releases
- macOS arm64: `deep-filter-0.5.6-aarch64-apple-darwin` → `/opt/homebrew/bin/deep-filter`
- Python `deepfilternet` pip package is broken: removes `torchaudio.backend.common.AudioMetaData`, downgrades numpy
- Expects 48kHz input → denoise → then downsample to 16kHz for ASR

## Phase-Specific Findings

### Phase 3: Audio Extraction
- Extract at 48kHz (not 16kHz) for DeepFilterNet
- Pipeline: `ffmpeg -ar 48000` → `deep-filter` → `ffmpeg -ar 16000` for ASR copy
- The 48kHz denoised file goes to final output; 16kHz version is for transcription only

### Phase 4: ASR / Chirp 2

**Critical location constraint:**
- Chirp 2 only exists in: `us-central1`, `europe-west4`, `asia-southeast1`
- Multi-language codes (e.g., `["ne-NP", "en-US"]`) require: `eu`, `global`, `us`
- These are **mutually exclusive** — you cannot use multi-language codes with Chirp 2
- Solution: use single `["ne-NP"]` — Chirp 2 handles English code-switching adequately

**Auto-detect is unreliable:**
- `language_codes=["auto"]` misidentified Nepali as Latin (confidence 0.62)
- Always specify `["ne-NP"]` explicitly

**Sync Recognize limit:**
- Maximum 60 seconds per request
- Split clips > 55s into 52s chunks with 3s overlap
- Merge by dropping words from chunk N+1 that have timestamps before the last word of chunk N

**API setup:**
```python
from google.api_core.client_options import ClientOptions
client = SpeechClient(
    client_options=ClientOptions(api_endpoint="us-central1-speech.googleapis.com")
)
# recognizer: "projects/agentshakti/locations/us-central1/recognizers/_"
```

### Phase 5: VAD + Pitch
- Silero VAD via `torch.hub` needs torchaudio (uses `read_audio` util internally)
- librosa pYIN works independently — pitch analysis succeeds even if VAD fails
- Run with `--force` to reprocess if VAD initially failed due to missing torchaudio

### Phase 7: Frame Extraction
- Manifest must use key `frames.extracted` (list of `{"path": "...", "time": ..., "reason": ...}`)
- The YOLO script (Phase 8) reads `clip.frames.extracted[].path` — if you use a different key name (e.g., `frame_list`), YOLO silently skips all frames
- Last-frame extraction at `duration - 0.05s` occasionally fails (~5/566 frames) — non-blocking

### Phase 8: YOLO
- Downloads models on first run: `yolo11x.pt` (~113MB) and `yolo11x-pose.pt` (~113MB)
- Processes ~10 frames/sec on Apple Silicon
- Needs torchvision matching torch version

## GoPro Footage Characteristics (Dec 2024 shoot)
- 19 clips at 2704×1520 @ 59.94fps (HEVC) + 1 clip at 3840×2160 @ 23.98fps
- Total: 496.2s (8m16s), 20 clips
- All camera type (no screen recordings in this batch)
- Nepali primary language with English code-switching
- Topic: "Starting content creation — equipment comparison"

### Phase 14: SFX Generation
- ElevenLabs `text_to_sound_effects.convert()` works well for whooshes, blips, transition sounds
- Generated files are small (16-28KB MP3s) — verify they're not silence
- SFX placement data MUST include concrete segment references (`after_segment`), not null — otherwise the FCPXML export cannot position them
- Transition SFX go at unit boundaries; within-unit SFX need `time_offset_seconds` from the segment start

### Phase 15: Music Generation
- **Gemini `response_modalities=["AUDIO"]` is TTS, not music** — it produces speech narration
- Use **Lyria 2** on Vertex AI (`lyria-002` model) for instrumental generation — GA, $0.06/30s clip
- Or **Lyria RealTime** (`models/lyria-realtime-exp`) via Gemini API WebSocket for streaming
- Lyria prompts must be US English. Output: 48kHz WAV (Lyria 2) or PCM16 stream (RealTime)
- If user provides a track, compute ducking keyframes from VAD/transcript data
- See `sfx-music-generation.md` for full API details and alternatives

### Phase 16b: Merge Units
- The merge must produce timeline data that matches what the FCPXML export expects:
  - Each segment needs an `id` field (e.g., `seg_000_clip_2461`)
  - `in_point` and `out_point` fields (not just `start`/`end`)
  - `timeline.order` as list of segment IDs (not `unit_order`)
  - Transitions need `from_segment`/`to_segment` (not `from_unit`/`to_unit`)
- All clips referenced by segments must exist in the main `clips[]` array — including animation clips and inserted media
- Use ffprobe to get actual durations, don't trust manifest values blindly

### Phase 17: FCPXML Export

**GoPro embedded timecodes:**
- GoPro cameras embed clock timecodes in a `tmcd` stream (e.g., `10:54:43:20`)
- DaVinci Resolve uses these as clip time addresses
- Setting FCPXML `start` to match the timecode fixes import but creates -11 hour timeline offset
- **Correct fix:** remux media files to strip tmcd: `ffmpeg -i in.mp4 -map 0:v:0 -map 0:a:0 -c copy -write_tmcd 0 out.mp4`
- Then use `start="0/1s"` everywhere in FCPXML

**Media consolidation:**
- DaVinci's "search for clips" does NOT search recursively
- All media files must be in a single flat directory (e.g., `exports/media/`)
- Copy all referenced files there (GoPro clips, animations, SFX, inserted media)

**FCPXML structural requirements:**
- **Frame boundary rule**: ALL time values must be exact multiples of `frameDuration`. For 29.97fps: `N*1001/30000s`. Violating → "not on edit frame boundary" error
- Volume keyframes: `<adjust-volume>` → `<param name="volume">` → `<keyframeAnimation>` → `<keyframe>` children. Lives on `<audio>` element, not `<asset-clip>`. Values are **linear gain** (0-1), not dB
- **DaVinci Resolve ignores volume keyframes on import** — known longstanding bug. Write them for FCP compatibility; store in manifest for manual DaVinci application
- **DaVinci also ignores audio transitions and roles metadata** on import
- Spine offsets: accumulate integer frame counts sequentially, never round floats independently (causes 1-frame overlaps)
- Cross Dissolve transitions between units, not between clips within the same unit
- SFX as connected clips (lane="1") attached to the correct spine clip
- Connected clip `offset` is relative to the PRIMARY STORYLINE timeline, not to the parent clip

**Background agent quality:**
- Background agents for SFX/music generation MUST verify their output before reporting success
- Always ffprobe generated files to confirm format, duration, and codec
- Always play-test or spot-check generated audio quality

## Manifest Format Expectations Between Phases

| Phase | Reads from manifest | Writes to manifest |
|-------|--------------------|--------------------|
| 3 (Audio) | `clip.symlink_path` | `clip.audio.{extracted_path, denoised_path, duration_seconds}` |
| 4 (ASR) | `clip.audio.duration_seconds` | `clip.transcript.{path, engine, word_count, segments}` |
| 5 (VAD/Pitch) | `clip.audio.{denoised_path, extracted_path}` | `clip.vad`, `clip.pitch` |
| 6 (Scenes) | `clip.symlink_path` or raw/ | `clip.scenes.boundaries[]` |
| 7 (Frames) | `clip.vad`, `clip.pitch`, `clip.scenes` | `clip.frames.{path, count, extracted[]}` |
| 8 (YOLO) | `clip.frames.extracted[].path` | `clip.yolo` |
| 9 (Vision) | Gemini Flash: `clip.symlink_path` (uploads video). Claude Vision: `clip.frames.extracted[].path` | `clip.vision.{backend, segments[], scene_boundaries[], per_frame[]}` |
