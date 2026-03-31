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
- Versioning via git auto-commit on each operation

### Server-Authoritative Edit Manifest (2026-03-14)
- All edit_manifest.json mutations go through `PATCH /api/edit-manifest` on the Express server (port 3001)
- Server reads file, applies operation atomically, writes back — single writer, no races
- Web UI sends operations with optimistic local apply + server confirmation
- Claude agents use the same HTTP endpoint when the studio server is running
- Fallback: when server is NOT running, agents use `units/{unit_id}/agent_output.json` merge queue
- Old full-document `POST /api/edit-manifest` is deprecated — still works but logs a warning
- No more dirty tracking, no more 30s sync interval, no more manual Ctrl+S sync
- Check if server is up: `curl -s http://localhost:3001/api/status`

### PRIORITY: Studio ↔ CLI Parity (2026-03-15)
**Every edit_manifest change MUST go through the studio server API when it is running.** This is non-negotiable. Direct file writes to edit_manifest.json bypass the server's atomic write guarantees and leave the studio UI out of sync.

**Before ANY edit_manifest mutation:**
1. Check if studio server is running: `curl -s http://localhost:3001/api/status`
2. If running → use `PATCH /api/edit-manifest` with typed operations
3. If NOT running → write to edit_manifest.json directly as fallback, but log a warning

**Operations that MUST use the API:**
- `reorder_units` — changing unit_order
- `set_unit_status` — marking units as reviewed/processed
- `add_word_cut` / `remove_word_cut` — transcript edits
- `set_trim` — in/out points
- `add_deleted_range` / `remove_deleted_range`
- `insert_unit` / `remove_unit`
- Any unit field mutation (instructions, display_name, etc.)

**Why this matters:** The user edits in the studio web app AND via Claude CLI. If Claude writes directly to the file while the studio is open, the studio's in-memory state diverges from disk. The server API ensures both see the same state.

**Direct file writes are ONLY acceptable when:**
- Studio server is confirmed NOT running
- Bulk migration/repair operations that would be impractical via individual API calls (document why)

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

### SFX prompt quality (critical — bad prompts = garbage output)

ElevenLabs produces good results ONLY with concrete, grounded prompts that describe real-world sounds. Abstract vibes produce unusable noise.

**BAD prompts (vague, abstract, made-up sounds):**
- "dramatic mathematical reveal sound, ethereal shimmer with subtle bass, scientific discovery feel"
- "autonomous AI processing sound, subtle robotic chirp with digital overtone"
- "gentle thinking bell shimmer, soft crystalline chime, moment of inspiration"
- "uplifting conclusion riser, building to a positive ending, warm"

These describe moods, not sounds. ElevenLabs doesn't know what a "scientific discovery feel" sounds like. Nobody does.

**GOOD prompts (concrete, physical, recordable sounds):**
- "mechanical keyboard typing, cherry mx blue switches, 3 keystrokes"
- "short whoosh, fast left to right, cinematic"
- "single camera shutter click, DSLR"
- "pop notification sound, like macOS or iPhone"
- "door closing, wooden door, indoor room"
- "mouse click, double click"

**Rules for SFX prompt writing:**
1. **Describe a physical sound source.** If you can't name a real object making the sound, the prompt is too abstract.
2. **Keep prompts short.** 5-10 words max. "short whoosh, fast" > "smooth cinematic whoosh transition, medium pace, left to right with subtle reverb"
3. **Use fewer SFX, placed better.** 3-4 well-placed sounds per unit max. Not every silence gap needs a swoosh. Not every topic shift needs a "transition sound." Most of the time, silence IS the transition.
4. **Read the transcript before choosing SFX.** The sound must relate to what's being SAID or SHOWN, not to abstract editorial concepts. If the speaker mentions "3D printer" → printer whir. If they mention "typing code" → keyboard clicks. If nothing concrete is mentioned → no SFX needed.
5. **Transition whooshes are overused.** One whoosh between major sections is fine. Six whooshes in a 47-second clip is annoying. Use silence, music ducking, or a simple cut instead.
6. **Never generate "riser" or "swell" SFX.** Those belong in the background music track, not as standalone SFX. A 2-second "uplifting conclusion riser" from ElevenLabs sounds terrible.

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

---

## Video Compilation / Direct Render (Phase 17 alternative)

When compiling units into a single rendered video (instead of NLE project export), these rules are mandatory:

### Edit manifest edits MUST be applied
Word cuts, trims, and deleted_ranges from the edit_manifest are NOT optional metadata — they are editorial decisions the user made. Every compilation MUST:
1. **Apply word_cuts**: Remove the exact time ranges of cut words from audio+video. These are "Descript-style" cuts — the user edited the transcript to remove filler words, and those time ranges must be physically removed from the output.
2. **Apply trims**: Only include content between `trim.in` and `trim.out`. Content outside the trim range does not exist.
3. **Apply deleted_ranges**: Skip these time ranges entirely.

Failure to apply these means shipping the user's raw footage with all the filler words they explicitly marked for removal. This is equivalent to ignoring the user's edit.

### ffmpeg amix: always use normalize=0
The `amix` filter divides volume by input count by default. With N SFX inputs, main audio drops to 1/N volume. ALWAYS use `normalize=0` and set explicit volume weights.

### Re-read edit_manifest immediately before compilation
The user may have made changes in the studio between when you started planning and when you render. Always read the current state of `edit_manifest.json` right before building the ffmpeg command.

### Distinguish video content from Claude instructions in footage
The user records footage while working. Some clips are content for the YouTube audience. Other clips are the user recording instructions for Claude — explaining on a whiteboard what to build, narrating what they want generated, describing an animation they need. These instruction clips are NOT content for the final video.

**The rule:** If the speaker recorded instructions for Claude about what to generate, that footage is the INPUT. The generated output (animation, composited video, etc.) is the CONTENT. Only the output goes in the final video.

**Example (unit_007):** The user drew on a whiteboard explaining "Claude needs to animate this using Remotion, pipeline goes F1→F2→F3→DaVinci..." — this is an instruction recording. Claude then generated `clip_animation_pipeline` (42.5s animation) from those instructions. The animation goes in the final video. The whiteboard recording does NOT.

**How to detect instruction footage:**
- Speaker references Claude/AI directly: "क्लोडले एनिमेट गर्नु पर्छ" ("Claude needs to animate"), "use Remotion", "rotoscope the person"
- Speaker is describing what they WANT built, not showing something that already exists
- The unit has both a raw recording AND a generated clip — the raw recording was the instruction, the generated clip is the output
- Marker instructions in edit_manifest point to the same content: if the studio instructions say "animate this whiteboard", the whiteboard clip is reference material, not content

**Do NOT ask the user which clips are instructions.** Read the transcript. If someone says "Claude should do X with Remotion", that's obviously not YouTube content.

### 9:16 Shorts: NEVER crop 16:9 — recompose from scratch

Converting 16:9 to 9:16 is NOT a crop/scale operation. It is a full recomposition. Cropping a 16:9 frame to 9:16 loses 68% of horizontal content — titles disappear, screen content gets cut, context is destroyed.

**What a proper 9:16 recomposition requires:**

1. **New Remotion project at 1080x1920** — not a filter on existing renders
2. **Use RAW source clips** — never use 16:9 VFX renders (they have baked-in typography that collides with vertical captions)
3. **YOLO face/person detection data** — use `analysis/yolo/` bounding boxes to dynamically position the crop window on the subject. Don't center-crop blindly — the person might be off-center, gesturing to one side, or holding up an object
4. **Content-aware framing per segment type:**
   - **Talking head**: Crop to face+shoulders using YOLO person bbox, bias toward top (head visible)
   - **Screen recording**: Do NOT crop — scale to fit width, fill remaining space with blurred BG or solid color. Screen content must be fully readable
   - **Animation (16:9 designed)**: Scale to fit within the vertical frame. Add context above/below (title, captions, branding). Never crop a diagram — it becomes illegible
   - **Whiteboard/handwriting**: Same as screen recording — readability over aesthetics
5. **Transcript-driven captions** — word-level timing from Chirp 2 ASR, large font (56-64px), overlay on video with semi-transparent pill backdrop. These are the ONLY captions — no baked-in 16:9 text
6. **Separate narration track** — shorts often work better with a dedicated voiceover recorded for vertical (faster pacing, more energy) rather than reusing the long-form audio
7. **Different pacing** — shorts need faster cuts, tighter segments, hook in first 2 seconds. Don't just trim the 16:9 edit — restructure for vertical attention patterns
8. **Title/text elements must be redesigned** — a 16:9 title at 120px font centered at x=960 gets cropped in 9:16. Design titles for 1080px width with safe margins

**What NOT to do:**
- `objectFit: "cover"` on a 16:9 source in a 9:16 frame — this is just cropping with extra steps
- Center-crop and call it "full bleed" — you're hiding the problem, not solving it
- Use the same VFX renders for both formats — the typography, HUD positions, and compositions are designed for 16:9
- Pan across a 16:9 diagram in 9:16 — the visible area at any moment shows mostly empty space

**Data available for recomposition:**
- `analysis/yolo/{clip_id}.json` — person/object bounding boxes per frame
- `analysis/transcripts/{clip_id}.json` — word-level timing (Chirp 2)
- `analysis/vad/{clip_id}.json` — speech/silence segments
- `analysis/vision/{clip_id}.json` — per-frame content description, interest scores
- `footage_manifest.json` — clip metadata, fps, resolution, classification

### Background music is not optional — but VOICE IS KING

Phase 15 music must be generated or sourced BEFORE compilation. A video without background music sounds amateur. BUT:

**The narrator's voice is the primary audio. Everything else serves it.**

- **Voice volume: 120% default.** Boost the narrator's audio above unity — slight compression + gain to make the voice punchy and forward. It sits IN FRONT of everything by default. CAN be ducked/reduced for specific sequences — e.g., lower during B-roll montage where ambient audio carries, or drop during a dramatic pause where music swells briefly. But it always comes back to 120% when the narrator is delivering content.
- **Background music volume: 3-5% during speech.** Not 8%, not 6%. THREE TO FIVE PERCENT. The music should be felt, not heard. If you can identify the melody while the narrator is talking, it's too loud.
- **Music during silence/pauses: 10-15% max.** Even when the narrator stops, the music doesn't take over. It fills the gap gently.
- **Music drops to ZERO before key statements.** JH signature move. The silence before "बहाना सकियो" or "१८२" is more powerful than any swell.
- **SFX volume: 20-30%.** Whooshes, dings, hits — audible but not jarring. They punctuate, they don't compete.

**The hierarchy (never violated):**
1. Narrator voice — 100%
2. SFX — 20-30%
3. Music during silence — 10-15%
4. Music during speech — 3-5%
5. B-roll audio — context-dependent. Let it breathe (5-15%) when it adds value: protest crowds, parliament murmur, street sounds, news broadcasts with relevant audio. Duck under narrator voice. The decision is EDITORIAL — sometimes a news anchor saying "Oli arrested" IS the point and should be heard. Don't make blanket rules. Judge per sequence.

**Common mistake:** Setting music to 6-8% and thinking "that's low." It's not. At 6% the music is clearly audible and competes with the voice, especially in quieter passages. 3% is where music becomes subconscious — you feel the energy without identifying the instrument.

### Audio transitions: always ease out, never hard cut
When cutting between segments (word cuts, trim boundaries, unit transitions), audio MUST have smooth transitions:

1. **Micro-fades at cut boundaries (80ms)**: Every trim/concat segment gets `afade=type=in:duration=0.08` at start and `afade=type=out:duration=0.08` at end. This prevents audio pops/clicks from hard cuts. 80ms is imperceptible as a fade but eliminates the jarring snap.
2. **Unit transition fades (400-500ms)**: Between units, use `afade` for smooth audio crossfade. The video gets a visual fade-to-black; the audio gets a matching fade-out/fade-in.
3. **Music ducking via sidechain compression**: Use `sidechaincompress` filter with speech as sidechain key, not manual volume keyframes. Parameters: `threshold=0.02:ratio=4:attack=200:release=800:mix=0.7`.
4. **Hook audio ease-out**: When the hook transitions to the first unit, the hook's audio (music/SFX) must ease out with `Easing.out(Easing.cubic)` or equivalent `afade` curve — never a hard stop.

**Bad**: `atrim=5:10,asetpts=PTS-STARTPTS` (hard cut at both ends)
**Good**: `atrim=5:10,asetpts=PTS-STARTPTS,afade=type=in:duration=0.08,afade=type=out:start_time=4.92:duration=0.08`

---

## Critical Failures from gov-karyasuchi Session (2026-03-29)

### 1. Retake Detection is Broken

**Problem:** Chirp 2 ASR with 52s chunking misses "retake" / "I'm gonna retake this" markers in later chunks of long clips. take_05 (186s) had a retake at 147.3s that was completely missed. It appeared in the uploaded YouTube video.

**Root cause:** Chunking with overlap deduplication drops words near boundaries. Long clips with sparse speech get poor coverage in later chunks. ASR returned only 72s of words for a 186s clip.

**Fix — Mandatory Retake Detection Step (post-Phase 4):**
1. After ASR, run a SEPARATE retake scan: extract 15s audio segments every 25s across the full clip
2. Transcribe each segment independently with Chirp 2 (not chunked)
3. Search for: "रिटेक", "गोइंग", "गोइङ", "रिटर्न", "सरी", "sorry", "retake", "फक"
4. Any match = retake marker. Log timestamp, cut video before that point.
5. OR: use Gemini Flash to scan the full video for moments where the speaker stops and says they want to retake
6. BEST: ask the creator to provide retake timestamps before pipeline starts

**Rule:** NEVER trust ASR alone for retake detection on clips >60s. Always do a dedicated second pass.

### 2. Animation Quality Cheapness Spiral

**Problem:** Claude defaults to the cheapest visual representation and the creator has to push back 3-4 times before getting something acceptable. The progression was: emoji icons → text labels → CSS shapes → actual mockup UIs. Only the mockup UIs were good.

**Root cause:** No quality standard in the spec. "Agents produce Remotion components" says nothing about WHAT those components should look like.

**Fix — Animation Quality Rules (add to Phase 13 spec):**
1. **NO emoji icons in any visual.** Not 📱, not 💰, not 🏛️. Every icon must be SVG or CSS-drawn.
2. **NO plain text as "animation."** "Server? Budget? कसले?" on a black screen is not a visual — it's a title card. Every concept needs a visual metaphor or mockup.
3. **Every government service item gets a UI mockup** showing what the service COULD look like. NID auto-fill → show a form filling itself. Health Portal → show a hospital search app. Betting ban → show a betting site getting blocked. The mockup IS the visual, not a description of it.
4. **Every data point gets a data viz** — not text. "25% GDP = remittance" needs a bar chart, not text on screen.
5. **B-roll from YouTube is mandatory context.** Every section where the narrator discusses a real-world topic (protests, farming, parliament) MUST have B-roll footage. Face-only for more than 8 seconds = visual failure.
6. **Verify every YouTube clip with Gemini** before using. Downloaded clips frequently show the wrong content (hospital info page instead of hospital queue, morning show instead of arrest footage).

### 3. Subagents CANNOT Do Creative Work

**Problem:** Spawned 4+ subagents for visual composition work. Every one produced garbage:
- "JH style fix" agent created 4 new component files but didn't use any of them
- "Emoji replacement" agent replaced emojis with text (equally cheap)
- Multiple agents writing to the same file (Master.tsx) caused corruption
- Re-sync agent was the only useful one (mechanical task: change numbers)

**Fix — Bright-Line Rule:**
- **Subagents: ONLY for mechanical tasks** — file downloads, ASR, ffprobe, searching YouTube, generating boilerplate code, running scripts
- **NEVER for: visual design, timing decisions, editorial judgment, component rewrites, style application**
- **NEVER spawn two agents that write to the same file**
- All creative/editorial work must be done directly by the main agent with full conversation context

### 4. Video Editing ≠ Code Compilation

**Problem:** The pipeline treats video production as: write code → compile → ship. Real video editing is: build → watch → adjust → watch → adjust → watch. Multiple renders were shipped without watching them.

**Fix — Mandatory Visual Verification:**
1. After EVERY sequence is built, render 3 frames (first, middle, last) and READ them
2. Before ANY full render, scrub through Remotion Studio and get creator approval
3. Before ANY YouTube upload, play the rendered video end-to-end
4. The pipeline must have explicit "WATCH THIS" gates, not just "compile and render"

### 5. Timeline Offset Math is Fragile

**Problem:** Hardcoded timeline offsets (T02, T03, T04, T05, T06A-E) cascade — one retake cut changes every downstream value. Multiple bugs from wrong offsets.

**Fix:**
- Use Remotion's `<Series>` component to auto-sequence takes instead of manual `from={f(T06B)}` math
- OR compute offsets dynamically from an array of clip segments, not constants
- ANY retake cut must trigger a full recalculation of all downstream offsets

### 6. Subtitle Sync Requires Careful Offset Management

**Problem (this session only):** Karaoke subtitles went out of sync after cut points because the word-to-timeline offset calculation was wrong. A previous session successfully implemented karaoke subs on a multi-take video — the system WORKS. This session broke it by:
1. Trying to replace ASR words with script text using even distribution (broke timing)
2. Not recalculating word offsets after adding retake cuts (T05B split)
3. Mixing approaches — raw ASR words one attempt, script words the next

**Fix — The correct approach (proven in previous sessions):**
1. Use raw ASR word timestamps as the PRIMARY timing source
2. For each take segment, shift ASR timestamps by the segment's global timeline offset
3. When a take is split (retake cut), create TWO word arrays with correct offsets for each segment
4. After ANY cut/trim change, rebuild the ENTIRE word file from scratch — never patch
5. If ASR text is too wrong for subtitles, manually correct the word text in the words.ts file WHILE KEEPING the ASR timestamps intact — never regenerate timestamps from script text

---

### Video transitions: context-appropriate, not mechanical
Do NOT use the same transition between every unit. Match transition style to editorial intent:

1. **Topic continuation**: Simple cut or 200ms crossfade — minimal interruption
2. **Topic change**: Fade-to-black (400ms fade + 200ms black gap) — signals new section
3. **Hook → content**: Music-driven transition — hook audio eases out while first unit fades in
4. **Demo → reaction**: Hard cut — maintains energy
5. **Closing**: Longer fade-out (800ms+) — signals end

The previous approach of identical fade-to-black between every pair made the video feel like a PowerPoint. Vary transitions based on the relationship between adjacent units.
