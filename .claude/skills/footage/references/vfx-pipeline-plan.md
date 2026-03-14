# VFX Composition Pipeline — Architecture Plan

This document specifies the VFX composition pipeline that runs after the footage analysis pipeline (phases 1-12). It takes analyzed, transcribed, and editorially organized units and composes them into fully rendered video using Remotion, with layered SFX and AI-generated music via ElevenLabs.

**Rendering target**: Remotion renders everything. Each unit is a Remotion composition. Final video is a master composition of all units. No Blender VSE. No FCPXML.

**Audio provider**: ElevenLabs for both SFX (Sound Effects v2) and music (Eleven Music). Replaces Lyria/Vertex AI.

---

## Phase Structure

The footage pipeline (phases 1-12) remains unchanged. Phases 13-20 are replaced:

```
EXISTING FOOTAGE PIPELINE (unchanged)
  Phase 1:  Setup + deps
  Phase 2:  Scan + classify (ffprobe, camera vs screencast)
  Phase 3:  Audio extraction + DeepFilterNet denoise + mux
  Phase 4:  ASR transcription (Chirp 2, ne-NP)
  Phase 5:  VAD + pitch analysis
  Phase 6:  Scene detection (OpenCV)
  Phase 7:  Frame extraction
  Phase 8:  YOLO detection (object + pose)
  Phase 9:  Vision analysis (Gemini Flash) ← EXTENDED with editorial beats
  Phase 10: Screen recording sync
  Phase 11: Narrative analysis + global timeline + unit decomposition
  Phase 12: Studio session (editorial decisions)

NEW VFX COMPOSITION PIPELINE
  Phase 13: VFX Pre-processing    ← ML: depth maps, segmentation masks (only for clips that need them)
  Phase 14: VFX + SFX Composition ← Claude builds per-unit Remotion composition specs from analysis
  Phase 15: Audio Generation      ← ElevenLabs: SFX + music, per-unit + global
  Phase 16: Remotion Build        ← Generate Remotion source code from composition specs
  Phase 17: Studio VFX Review     ← User reviews in studio with Remotion Player preview
  Phase 18: Unit Render           ← Remotion renders each unit to video
  Phase 19: Global Composition    ← Master composition: inter-unit transitions, music, global effects
  Phase 20: Final Render + YouTube metadata + cleanup
```

---

## Phase 9 Extension: Editorial Intelligence

Gemini Flash already watches the full video (audio + visual) in Phase 9. Extend its structured output to include editorial analysis.

### Extended Phase 9 Output Schema

Add to `clip.vision` (alongside existing `segments[]`, `scene_boundaries[]`, `per_frame[]`):

```json
{
  "editorial_beats": [
    {
      "id": "eb_001",
      "time": 45.2,
      "end_time": 48.0,
      "type": "reveal",
      "intensity": "high",
      "description": "Speaker reveals key statistic after buildup",
      "transcript_excerpt": "...and that's when I found out it was forty seven percent",
      "suggested_treatment": {
        "typography": {
          "text": "47%",
          "style": "impact_number",
          "language": "en"
        },
        "sfx_layers": ["emphasis_hit", "subtle_riser_before"],
        "camera": "slow_zoom_in",
        "pacing": "hold_3s_after"
      }
    },
    {
      "id": "eb_002",
      "time": 62.0,
      "end_time": 70.0,
      "type": "evidence_sequence",
      "intensity": "medium",
      "description": "References multiple sources in rapid succession",
      "suggested_treatment": {
        "pacing": "rapid_cuts",
        "cut_duration_seconds": 0.3,
        "sfx_layers": ["camera_click_per_cut"],
        "texture": "film_grain_heavy"
      }
    },
    {
      "id": "eb_003",
      "time": 98.5,
      "end_time": 103.0,
      "type": "emotional_pause",
      "intensity": "low",
      "description": "Speaker pauses after heavy statement — let it breathe",
      "suggested_treatment": {
        "camera": "hold_still",
        "sfx_layers": ["ambient_only"],
        "music": "drop_to_silence",
        "pacing": "hold_4s"
      }
    }
  ],

  "pacing_map": [
    {
      "range": [0, 30],
      "energy": "high",
      "rhythm": "fast_cuts",
      "music_mood": "energetic"
    },
    {
      "range": [30, 60],
      "energy": "medium",
      "rhythm": "steady",
      "music_mood": "contemplative"
    },
    {
      "range": [60, 90],
      "energy": "building",
      "rhythm": "accelerating",
      "music_mood": "tension_building"
    },
    {
      "range": [90, 105],
      "energy": "peak",
      "rhythm": "rapid",
      "music_mood": "climactic"
    },
    {
      "range": [105, 120],
      "energy": "low",
      "rhythm": "contemplative",
      "music_mood": "reflective"
    }
  ],

  "typography_candidates": [
    {
      "id": "tc_001",
      "time": 45.2,
      "text": "47%",
      "text_nepali": null,
      "reason": "key statistic, speaker emphasizes with pitch rise",
      "style": "impact_number",
      "duration_seconds": 2.5,
      "position": "center"
    },
    {
      "id": "tc_002",
      "time": 72.0,
      "text": "Treaty of Sugauli",
      "text_nepali": "सुगौली सन्धि",
      "reason": "historical reference, first mention, viewer needs visual anchor",
      "style": "label",
      "duration_seconds": 3.0,
      "position": "lower_third"
    }
  ]
}
```

### Editorial Beat Types

| Type | Description | Typical Treatment |
|---|---|---|
| `reveal` | Key fact, statistic, or insight disclosed | Slow zoom + impact number typography + emphasis SFX |
| `evidence_sequence` | Rapid references to multiple sources | Fast cuts (0.2-0.5s each) + camera clicks + film grain |
| `emotional_pause` | Deliberate silence after heavy statement | Hold still + drop music + ambient only |
| `humor` | Comedic beat or unexpected twist | Speed ramp or freeze frame + comedic SFX |
| `transition` | Topic shift or segment change | Transition VFX + whoosh/riser SFX |
| `buildup` | Tension escalation toward reveal | Accelerating cuts + rising music + subtle zoom |
| `demo` | Technical demonstration or walkthrough | Clean framing + UI SFX + typography labels |
| `callout` | Direct address to viewer or rhetorical question | Ken Burns zoom + emphasis + text |
| `context` | Background information or setup | Steady pacing + lower-third labels + ambient |
| `cold_open` | Hook in first 30 seconds | High energy + rapid visuals + strong SFX |

### Heuristic Pre-suggestions (Layer 1 — free)

These are derived from existing analysis data without any API call:

```
pitch_peak + transcript_keyword_match("percent|प्रतिशत|number|data")
  → typography candidate (impact_number style)

silence_gap > 0.5s + preceding_speech_segment.confidence > 0.8
  → transition candidate

scene_boundary(type="cut") + energy_change
  → transition SFX candidate

vad.speech_start after silence > 1.0s
  → ambient bed modulation point

yolo.person_detected + interest_score > 0.7
  → background blur candidate

clip.type == "screen_recording"
  → UI SFX layer active

pitch.emphasis_point(type="rise", magnitude > 0.6)
  → emphasis SFX candidate

consecutive_short_segments(count > 3, duration < 2s each)
  → evidence_sequence pacing pattern
```

---

## Phase 13: VFX Pre-processing

Only runs for clips that need ML-heavy effects. Skipped entirely if no tier 2/3 effects are assigned.

### Assets Generated

| Asset | Tool | Output | When needed |
|---|---|---|---|
| Depth map | MiDaS v3.1 (DPT-Large) | Grayscale video, same fps as source | Background blur, dolly zoom |
| Segmentation mask | SAM2 | Alpha video (person mask) | Rotoscoping |
| Optical flow | RAFT | Flow field video | Motion smear |
| Style transfer | ReReVST (temporal consistent) | Stylized video | Neural style transfer |

### Storage

```
analysis/vfx/
  depth/{clip_id}_depth.mp4
  masks/{clip_id}_mask.mp4
  flow/{clip_id}_flow.npy     (or .mp4 visualization)
  style/{clip_id}_{style_name}.mp4
```

### Manifest Extension

Add to `clip` in `footage_manifest.json`:

```json
{
  "vfx_assets": {
    "depth_map": {
      "path": "analysis/vfx/depth/clip_001_depth.mp4",
      "model": "midas_dpt_large",
      "fps": 30,
      "resolution": [1920, 1080]
    },
    "segmentation_mask": {
      "path": "analysis/vfx/masks/clip_001_mask.mp4",
      "model": "sam2",
      "fps": 30,
      "subject": "person",
      "quality_score": 0.92
    },
    "optical_flow": {
      "path": "analysis/vfx/flow/clip_001_flow.npy",
      "model": "raft"
    },
    "style_transfer": {
      "style_name": "monet",
      "path": "analysis/vfx/style/clip_001_monet.mp4",
      "model": "rerevst"
    }
  }
}
```

### Processing Budget (M3 Max estimates)

| Asset | Speed | 60s clip at 30fps (1800 frames) | Notes |
|---|---|---|---|
| MiDaS depth | ~8-12 fps on MPS | 2.5-4 min | Single pass, no temporal |
| SAM2 mask | ~2-4 fps on MPS | 7-15 min | Propagate from key frames |
| RAFT flow | ~5-8 fps on MPS | 4-6 min | Consecutive frame pairs |
| ReReVST style | ~1-3 fps on MPS | 10-30 min | Temporal consistency pass |

Only process the time ranges that need effects, not full clips.

---

## Phase 14: VFX + SFX Composition

Claude reads ALL analysis data (transcript, editorial beats, pacing map, heuristic suggestions, user instructions from studio, markers) and builds a **composition spec** for each unit.

### Composition Spec Schema

Written to `units/{unit_id}/composition_spec.json`:

```json
{
  "unit_id": "unit_001",
  "version": "1.0.0",
  "fps": 30,
  "resolution": [1920, 1080],
  "duration_frames": 4500,

  "clips": [
    {
      "id": "tc_001",
      "source": "raw/clip_001.mp4",
      "in_point": 5.0,
      "out_point": 23.5,
      "timeline_start_frame": 0,
      "timeline_end_frame": 555,
      "speed": 1.0,
      "effects": [
        {
          "id": "vfx_001",
          "type": "background_blur",
          "params": {
            "depth_map": "analysis/vfx/depth/clip_001_depth.mp4",
            "blur_amount": 8,
            "focus_subject": "person",
            "fade_in_frames": 15,
            "fade_out_frames": 15
          },
          "start_frame": 0,
          "end_frame": 555,
          "coupled_sfx": null
        },
        {
          "id": "vfx_002",
          "type": "ken_burns_zoom",
          "params": {
            "start_rect": [0, 0, 1920, 1080],
            "end_rect": [640, 200, 1280, 720],
            "easing": "SINE"
          },
          "start_frame": 300,
          "end_frame": 450,
          "coupled_sfx": "sfx_003"
        }
      ]
    }
  ],

  "transitions": [
    {
      "id": "tr_001",
      "type": "whip_pan",
      "from_clip": "tc_001",
      "to_clip": "tc_002",
      "duration_frames": 12,
      "params": {
        "direction": "left_to_right",
        "blur_amount": 40
      },
      "coupled_sfx": "sfx_001"
    }
  ],

  "overlays": [
    {
      "id": "ovl_001",
      "type": "kinetic_text",
      "start_frame": 900,
      "duration_frames": 75,
      "params": {
        "text": "47%",
        "text_nepali": null,
        "style": "impact_number",
        "font": "Poppins",
        "weight": 700,
        "size_px": 180,
        "color": "#FF6B35",
        "position": "center",
        "animation": "scale_bounce_in",
        "exit_animation": "fade_out"
      },
      "coupled_sfx": "sfx_005"
    },
    {
      "id": "ovl_002",
      "type": "kinetic_text",
      "start_frame": 2160,
      "duration_frames": 90,
      "params": {
        "text": "सुगौली सन्धि",
        "text_secondary": "Treaty of Sugauli, 1816",
        "style": "label",
        "font_primary": "Noto Sans Devanagari",
        "font_secondary": "Inter",
        "weight": 600,
        "size_px": 48,
        "color": "#FFFFFF",
        "background": "rgba(26, 26, 46, 0.85)",
        "position": "lower_third",
        "animation": "slide_up",
        "exit_animation": "slide_down"
      },
      "coupled_sfx": "sfx_006"
    }
  ],

  "global_effects": {
    "film_grain": {
      "intensity": 0.15,
      "size": 1.5,
      "speed": 24
    },
    "light_leaks": {
      "enabled": true,
      "frequency": "on_transitions",
      "intensity": 0.3,
      "warmth": 0.7
    },
    "color_grade": {
      "type": "parametric",
      "temperature_shift": 200,
      "tint_shift": 5,
      "saturation": 0.9,
      "contrast": 1.1,
      "shadows_hue": 240,
      "highlights_hue": 40
    },
    "vignette": {
      "amount": 0.25,
      "roundness": 0.8
    }
  },

  "sfx": [
    {
      "id": "sfx_001",
      "layer": "transition",
      "description": "whoosh left-to-right for whip pan transition",
      "prompt": "fast left-to-right whoosh transition sound, cinematic, short and punchy",
      "start_frame": 549,
      "duration_seconds": 0.5,
      "volume_db": -6.0,
      "coupled_to_vfx": "tr_001",
      "generated_path": null,
      "cached_hash": null
    },
    {
      "id": "sfx_003",
      "layer": "emphasis",
      "description": "subtle riser swell for Ken Burns zoom",
      "prompt": "subtle cinematic riser swell, 3 seconds, building tension, ends with soft resolution",
      "start_frame": 285,
      "duration_seconds": 3.0,
      "volume_db": -12.0,
      "coupled_to_vfx": "vfx_002",
      "generated_path": null,
      "cached_hash": null
    },
    {
      "id": "sfx_005",
      "layer": "foley",
      "description": "impact pop for 47% number appearing",
      "prompt": "sharp impact pop with subtle bass thud, short punchy, clean, for text reveal",
      "start_frame": 900,
      "duration_seconds": 0.3,
      "volume_db": -8.0,
      "coupled_to_vfx": "ovl_001",
      "generated_path": null,
      "cached_hash": null
    },
    {
      "id": "sfx_006",
      "layer": "foley",
      "description": "soft slide sound for lower-third label",
      "prompt": "soft paper slide whoosh, subtle, professional, lower-third text reveal",
      "start_frame": 2160,
      "duration_seconds": 0.4,
      "volume_db": -10.0,
      "coupled_to_vfx": "ovl_002",
      "generated_path": null,
      "cached_hash": null
    }
  ],

  "ambient_beds": [
    {
      "id": "amb_001",
      "description": "indoor room tone with subtle air conditioning hum",
      "prompt": "quiet indoor room tone, subtle air conditioning hum, very soft background noise",
      "start_frame": 0,
      "end_frame": 4500,
      "volume_db": -28.0,
      "loop": true,
      "fade_in_seconds": 2.0,
      "fade_out_seconds": 2.0,
      "generated_path": null
    }
  ]
}
```

### Composition Decision Process

Claude follows this process for each unit:

1. **Read all analysis data**: transcript (word-level), editorial beats (from Gemini), pacing map, heuristic pre-suggestions, VAD, pitch, scenes, YOLO, vision
2. **Read user instructions**: from edit_manifest (markers, instructions textarea, word cuts)
3. **Read style config**: colors, fonts, Remotion settings
4. **Build effect plan**: For each segment of the unit, decide:
   - Which clip-level effects (blur, Ken Burns, rotoscope, speed ramp, grain)
   - Which transitions between clips
   - Which overlays (kinetic text — both Nepali and English)
   - Which SFX per layer, coupled to which VFX
   - Pacing decisions (cut timing, hold durations)
5. **Write composition_spec.json**: The complete spec that Remotion will consume
6. **Write to claude_notes**: Reasoning for each decision (why this effect here, why this SFX)

---

## Phase 15: Audio Generation (ElevenLabs)

All audio generation runs here — SFX and music. Both use ElevenLabs APIs.

### SFX Generation (ElevenLabs Sound Effects v2)

**API**: `POST https://api.elevenlabs.io/v1/sound-generation`

```python
from elevenlabs import ElevenLabs

client = ElevenLabs()  # ELEVENLABS_API_KEY from env

result = client.text_to_sound_effects.convert(
    text="fast left-to-right whoosh transition sound, cinematic, short and punchy",
    duration_seconds=0.5,
    model_id="eleven_text_to_sound_v2",
    prompt_influence=0.5,     # 0-1, higher = more literal
    output_format="pcm_48000" # 48kHz PCM for max quality
)

audio_bytes = b"".join(result)
with open("sfx/sfx_001.wav", "wb") as f:
    f.write(audio_bytes)
```

**Parameters**:
- `text`: Descriptive prompt (specific: material, environment, intensity, speed)
- `duration_seconds`: 0.5 to 30.0
- `loop`: boolean (for ambient beds)
- `prompt_influence`: 0.0-1.0 (default 0.3, higher = more literal adherence)
- `model_id`: `eleven_text_to_sound_v2`
- `output_format`: `pcm_48000` (48kHz PCM)

### SFX Five-Layer System

```
Layer 5:  UI sounds         ─ digital interactions, notifications, glitches
Layer 4:  Foley             ─ camera clicks, paper, typing, impacts, reveals
Layer 3:  Emphasis          ─ hits, stingers, bass drops, snaps, risers
Layer 2:  Transition        ─ whooshes, sweeps, booms, reverse cymbals
Layer 1:  Ambient bed       ─ room tone, outdoor atmosphere, hum (looped)
Layer 0:  Music             ─ background track with ducking (separate system)
```

### SFX-VFX Coupling Rules

Each VFX effect has a default SFX coupling. Coupling means the SFX is generated and placed automatically when the VFX is applied. User can remove or replace the coupled SFX.

| VFX Effect | Default Coupled SFX | Layer | Notes |
|---|---|---|---|
| `ken_burns_zoom` | Subtle riser/swell | emphasis | Duration matches zoom duration |
| `background_blur` (onset) | Soft low-pass sweep | emphasis | 0.3s at blur start |
| `rotoscope` (reveal) | Dramatic swell + hit | emphasis + transition | On the frame where composite activates |
| `speed_ramp` (slow-mo) | Time-stretch sound, low rumble | emphasis | Duration of slow-mo section |
| `speed_ramp` (fast) | Quick whoosh | transition | Short, 0.2-0.3s |
| `whip_pan` transition | Directional whoosh | transition | Panned L→R or R→L matching direction |
| `mask_reveal` transition | Paper/fabric unfold | transition | 0.3-0.5s |
| `glitch` transition | Digital glitch burst | transition + UI | Short burst + digital artifact |
| `dissolve` transition | None (silence is intentional) | — | Clean transitions need no SFX |
| `light_leak` transition | Soft shimmer | transition | Very subtle, -18dB |
| `kinetic_text` (impact) | Pop/hit | foley | Short, 0.2-0.3s, timed to text landing |
| `kinetic_text` (label) | Soft slide/whoosh | foley | Subtle, 0.3-0.4s |
| `kinetic_text` (Nepali) | Same as English equivalent | foley | No different treatment for language |
| `datamosh` transition | Glitch + digital noise | transition + UI | Layered: glitch burst + digital artifacts |
| `film_grain` (global) | None | — | Visual-only, no SFX coupling |
| `color_grade` (global) | None | — | Visual-only |

### SFX Caching

Generated SFX are cached by prompt hash to avoid re-generating identical sounds:

```
sfx/
  cache/
    {sha256_of_prompt_and_params}.wav
  sfx_001.wav → cache/{hash}.wav  (symlink)
  sfx_002.wav → cache/{hash}.wav
```

If a prompt+duration+influence hash matches an existing cached file, skip generation. Over time this builds a per-project SFX library.

### SFX Prompt Construction Rules

Claude constructs SFX prompts following these rules (not the user — the user describes intent, Claude translates to audio-appropriate prompts):

1. **Be specific about material and texture**: "wooden door creak" not "door sound"
2. **Include spatial context**: "close-mic impact" vs "distant reverberant boom"
3. **Specify duration character**: "short punchy 0.2s" vs "slow building 3s swell"
4. **Include energy level**: "subtle" vs "dramatic" vs "explosive"
5. **Match the content tone**: Tech videos → clean digital sounds. Politics → dramatic cinematic. Humor → playful, lighter SFX.
6. **Never generic**: "transition sound" → FAIL. "Fast left-to-right whoosh, cinematic, short" → GOOD.

### Music Generation (ElevenLabs Eleven Music)

**API**: `POST https://api.elevenlabs.io/v1/music`

```python
from elevenlabs import ElevenLabs

client = ElevenLabs()

# Simple prompt (for single-mood sections)
result = client.music.compose(
    model_id="music_v1",
    prompt="subtle ambient electronic, warm pads, gentle rhythm, contemplative mood, no vocals",
    music_length_ms=120000,  # 2 minutes
    force_instrumental=True,
    output_format="pcm_48000"
)

# Composition plan (for structured multi-section music)
result = client.music.compose(
    model_id="music_v1",
    composition_plan={
        "positive_global_styles": ["cinematic", "ambient electronic", "warm"],
        "negative_global_styles": ["aggressive", "harsh", "vocals", "singing"],
        "sections": [
            {
                "section_name": "intro",
                "positive_local_styles": ["atmospheric", "sparse", "building"],
                "negative_local_styles": ["loud", "busy"],
                "duration_ms": 15000,
                "lines": []
            },
            {
                "section_name": "main",
                "positive_local_styles": ["rhythmic", "engaging", "warm bass"],
                "negative_local_styles": ["aggressive"],
                "duration_ms": 90000,
                "lines": []
            },
            {
                "section_name": "climax",
                "positive_local_styles": ["energetic", "dramatic", "full"],
                "negative_local_styles": ["sparse"],
                "duration_ms": 30000,
                "lines": []
            },
            {
                "section_name": "outro",
                "positive_local_styles": ["fading", "reflective", "minimal"],
                "negative_local_styles": ["energetic"],
                "duration_ms": 15000,
                "lines": []
            }
        ]
    },
    force_instrumental=True,
    output_format="pcm_48000"
)
```

**Parameters**:
- `model_id`: `"music_v1"` (required)
- `prompt` OR `composition_plan` (mutually exclusive)
- `music_length_ms`: 3000-600000 (3s to 5min), only with `prompt`
- `force_instrumental`: `true` (ALWAYS — we never want vocals)
- `seed`: uint32 for reproducibility (only with `composition_plan`)
- `output_format`: `pcm_48000` (48kHz PCM)

### Music Composition Strategy

Music is generated to match the pacing map from Phase 9 editorial analysis:

1. **Map pacing sections to music sections**:
   - `energy: "high"` → positive_local_styles: ["energetic", "driving"]
   - `energy: "medium"` → positive_local_styles: ["steady", "rhythmic"]
   - `energy: "building"` → positive_local_styles: ["building", "rising"]
   - `energy: "peak"` → positive_local_styles: ["climactic", "full", "dramatic"]
   - `energy: "low"` → positive_local_styles: ["minimal", "reflective", "sparse"]

2. **Derive global styles from content type**:
   - Tech topics: ["ambient electronic", "minimal", "clean", "modern"]
   - Politics/history: ["cinematic", "orchestral undertones", "dramatic"]
   - Tutorial/demo: ["lo-fi", "chill", "unobtrusive", "background"]
   - Mix: ["hybrid", "versatile", "adaptive"]

3. **Generate per-unit music** (not one track for whole video):
   - Each unit gets its own music track matched to its pacing
   - Global composition (Phase 19) crossfades between unit tracks
   - User can regenerate any unit's music independently

4. **Ducking keyframes from VAD data**:
   ```
   speech_start - 0.3s  → duck to -26dB (attack)
   speech_end   + 0.8s  → raise to -18dB (release)
   silence > 2.0s       → raise to -14dB (more presence)
   ```

### Per-Section Music Regeneration

User can request regeneration of specific music sections from the studio:
- "Regenerate music for unit_003" → re-compose with same pacing map, different seed
- "Make unit_003 music more energetic" → modify positive_local_styles, regenerate
- "I don't like the climax section" → regenerate only that section of the composition plan

This is exposed in the studio VFX panel as a "Regenerate Music" button per unit with an optional style override textarea.

---

## Phase 16: Remotion Build

Generate Remotion source code from composition specs.

### Project Structure

```
studio/remotion/
  src/
    index.ts                    ← Register all compositions
    Root.tsx                    ← Root component

    compositions/
      UnitComposition.tsx       ← Generic unit renderer (data-driven from spec)
      MasterComposition.tsx     ← Stitches all units with inter-unit transitions
      PreviewComposition.tsx    ← Lightweight preview (skips heavy effects)

    effects/
      clip-level/
        BackgroundBlur.tsx      ← Depth map + gaussian blur
        KenBurnsZoom.tsx        ← Animated crop/scale on video
        Rotoscope.tsx           ← Mask compositing (subject over new background)
        SpeedRamp.tsx           ← Variable speed with frame interpolation
        DollyZoom.tsx           ← Depth-aware FOV simulation
        ChromaKey.tsx           ← Green screen removal
        NeuralStyle.tsx         ← Overlay pre-rendered stylized video
        MotionSmear.tsx         ← Directional blur from optical flow

      global/
        FilmGrain.tsx           ← Animated noise overlay
        LightLeaks.tsx          ← Warm light leak overlay, blended
        ColorGrade.tsx          ← Parametric color adjustments
        Vignette.tsx            ← Edge darkening

    transitions/
      WhipPan.tsx               ← Motion blur directional
      MaskReveal.tsx            ← Shape mask animation (circle, rect, custom)
      GlitchTransition.tsx      ← RGB split + displacement
      Dissolve.tsx              ← Crossfade
      FadeBlack.tsx             ← Fade to/from black
      LightLeakTransition.tsx   ← Light leak overlay during transition
      DatamoshTransition.tsx    ← Pre-rendered datamosh clip overlay
      ZoomThrough.tsx           ← Push into outgoing, pull out from incoming

    typography/
      KineticText.tsx           ← Base kinetic text component
      ImpactNumber.tsx          ← Large number reveal (scale bounce)
      LabelText.tsx             ← Lower-third label with background
      HeadlineText.tsx          ← Full-screen headline
      QuoteText.tsx             ← Attributed quote display
      DevanagariText.tsx        ← Nepali-aware text with proper shaping
      BilingualText.tsx         ← Primary Nepali + secondary English (or vice versa)

    audio/
      SFXLayer.tsx              ← Renders SFX at specified frames
      AmbientBed.tsx            ← Looping ambient with fades
      MusicTrack.tsx            ← Background music with ducking keyframes
      AudioMixer.tsx            ← Combines all audio layers with volume automation

    lib/
      easing.ts                 ← BEZIER, SINE, EXPO, BACK, ELASTIC, BOUNCE, CONSTANT
      color-grade.ts            ← Color manipulation utilities
      depth-utils.ts            ← Depth map sampling for blur/dolly
      text-measure.ts           ← Text measurement for Devanagari layout
      spring-presets.ts         ← Remotion spring configs for different animation feels

  remotion.config.ts
  package.json
```

### Data Flow

```
composition_spec.json  →  UnitComposition.tsx (reads spec as props)
                              ├── SourceClip (video with in/out points)
                              │     ├── BackgroundBlur (if assigned)
                              │     ├── KenBurnsZoom (if assigned)
                              │     └── Rotoscope (if assigned)
                              ├── Transition (between clips)
                              │     └── coupled SFX
                              ├── Overlay[]
                              │     ├── KineticText / DevanagariText
                              │     └── coupled SFX
                              ├── GlobalEffects
                              │     ├── FilmGrain
                              │     ├── LightLeaks
                              │     ├── ColorGrade
                              │     └── Vignette
                              └── AudioMixer
                                    ├── SFXLayer (all 5 layers)
                                    ├── AmbientBed
                                    └── MusicTrack
```

### UnitComposition.tsx (core rendering logic)

The unit composition is **entirely data-driven**. It reads the `composition_spec.json` and renders accordingly. No hardcoded editorial decisions in Remotion code — all decisions live in the spec.

```tsx
// Pseudocode structure
const UnitComposition: React.FC<{spec: CompositionSpec}> = ({spec}) => {
  return (
    <AbsoluteFill>
      {/* Layer 1: Source footage clips with effects */}
      <ClipSequence clips={spec.clips} transitions={spec.transitions} />

      {/* Layer 2: Overlays (typography, graphics) */}
      <OverlayLayer overlays={spec.overlays} />

      {/* Layer 3: Global visual effects */}
      <GlobalEffects config={spec.global_effects} />

      {/* Audio: all SFX layers + ambient + music */}
      <AudioMixer
        sfx={spec.sfx}
        ambient={spec.ambient_beds}
        music={spec.music}
      />
    </AbsoluteFill>
  );
};
```

---

## Phase 17: Studio VFX Review

The studio is extended with VFX capabilities.

### Studio UI Changes

**New: VFX Panel (below the player tab)**

When a unit is selected, a collapsible VFX panel appears below the player:

```
┌─────────────────────────────────────────────┐
│ Player (HTML5 video for raw footage)        │
│                                              │
│ [Play] [<<] [>>] [Frame: 00:01:23:15]       │
├─────────────────────────────────────────────┤
│ VFX Panel                            [▾ ▴]  │
│                                              │
│ ☑ Film Grain (0.15)              [Edit] [×]  │
│ ☑ Light Leaks (on transitions)   [Edit] [×]  │
│ ☑ Color Grade (warm)             [Edit] [×]  │
│ ☑ Vignette (0.25)                [Edit] [×]  │
│                                              │
│ Clip: tc_001 (0:05 → 0:23.5)                │
│   ☑ Background Blur (8px)        [Edit] [×]  │
│   ☑ Ken Burns Zoom (0:10-0:15)   [Edit] [×]  │
│                                              │
│ Transition: tc_001 → tc_002                  │
│   ☑ Whip Pan (L→R, 12f)         [Edit] [×]  │
│   └ 🔊 Whoosh (coupled)          [🔇] [×]    │
│                                              │
│ Typography:                                  │
│   ☑ "47%" @ 0:15.0 (impact)     [Edit] [×]  │
│   └ 🔊 Pop (coupled)             [🔇] [×]    │
│   ☑ "सुगौली सन्धि" @ 0:24.0    [Edit] [×]  │
│   └ 🔊 Slide (coupled)           [🔇] [×]    │
│                                              │
│ SFX Layers:                                  │
│   🔊 Ambient: Indoor room tone   [🔇] [×]    │
│   🔊 Emphasis: Riser @ 0:10     [🔇] [×]    │
│                                              │
│ Music:                                       │
│   🎵 Ambient electronic (2:00)  [🔇] [Redo]  │
│   Style: contemplative → building → peak     │
│                                              │
│ ── AI Suggestions ──────────────────────     │
│   ○ Add rotoscope @ 0:30-0:45   [Apply] [×]  │
│   ○ Speed ramp slow-mo @ 0:42   [Apply] [×]  │
│                                              │
│ [Preview in Remotion]  [Sync]                │
├─────────────────────────────────────────────┤
│ Elements | Precision                         │
└─────────────────────────────────────────────┘
```

**Key interactions:**
- **Checkbox (☑/○)**: Toggle effect on/off (stays in spec but `enabled: false`)
- **[Edit]**: Opens params editor (sliders, dropdowns, text inputs)
- **[×]**: Remove effect entirely (removes from spec + removes coupled SFX)
- **[🔇]**: Mute individual SFX (keeps in spec but `volume_db: -Infinity`)
- **[Redo]**: Regenerate (music or SFX) with modified prompt
- **[Apply]**: Accept AI suggestion (moves from suggestions to active effects)
- **[Preview in Remotion]**: Opens Remotion Player in a new panel/tab showing the composed unit
- **[Sync]**: Saves composition_spec.json + edit_manifest.json

**New: Remotion Preview Tab**

Alongside the existing Player tab, add a "Preview" tab that embeds the Remotion `<Player>` component. This renders the composed unit in real-time (or near-real-time for lightweight effects). Heavy effects (rotoscoping, style transfer) show as placeholder overlays until the pre-processing is done.

### Edit Manifest Extension

Add to `edit_manifest.json → units[unitId]`:

```json
{
  "vfx_overrides": {
    "disabled_effects": ["vfx_003"],
    "disabled_sfx": ["sfx_005"],
    "param_overrides": {
      "vfx_001": { "blur_amount": 12 },
      "ovl_001": { "size_px": 220, "color": "#F7C948" }
    },
    "music_style_override": "make it more energetic, faster rhythm",
    "music_regenerate_requested": false,
    "sfx_regenerate_requested": {
      "sfx_003": "make it more subtle, less dramatic"
    }
  }
}
```

The studio writes overrides. Phase 16 (Remotion Build) reads `composition_spec.json` + applies `vfx_overrides` from edit manifest to produce the final Remotion composition props.

---

## Kinetic Typography System — Devanagari Priority

### Design Principles

1. **Devanagari is primary, English is secondary** — when both appear, Nepali text is larger/more prominent
2. **Syllable-aware animation** — Devanagari characters form conjuncts (half-forms, ligatures). Animations must operate on syllable clusters, not individual Unicode codepoints. `"सन्धि"` = 3 syllables `स` `न्` `धि`, not 5 codepoints.
3. **Font stack**: Noto Sans Devanagari (primary Nepali), Poppins (English headings), Inter (English body)
4. **Bilingual labels**: Nepali on top (larger), English below (smaller, lighter color). Never side-by-side — vertical stack.

### Typography Styles

| Style | Use case | Animation | Example |
|---|---|---|---|
| `impact_number` | Key statistics, percentages | Scale bounce in from 0 → 1.2 → 1.0, with spring | "47%" |
| `label` | Lower-third identifiers, names, places | Slide up with background bar | "सुगौली सन्धि / Treaty of Sugauli" |
| `headline` | Section titles, topic headers | Character-by-character reveal L→R | "नेपालको सीमा विवाद" |
| `quote` | Direct quotes, citations | Fade in with quotation marks + attribution | "— प्रधानमन्त्री, २०२४" |
| `data_callout` | Data points, small facts | Pop in with subtle bounce | "स्थापना: १८१६" |
| `subtitle_emphasis` | Key spoken words displayed on screen | Typewriter-style, synced to speech timing | Individual words timed to audio |

### Devanagari-Specific Implementation

```tsx
// DevanagariText.tsx must handle:

// 1. Syllable segmentation (using Intl.Segmenter)
const segmenter = new Intl.Segmenter('ne', { granularity: 'grapheme' });
const syllables = [...segmenter.segment(text)].map(s => s.segment);

// 2. Per-syllable animation timing
// Each syllable gets its own spring/interpolation offset
// Character-by-character reveal respects syllable boundaries

// 3. Conjunct handling
// "न्" (na halant) is one grapheme cluster, not two characters
// The segmenter handles this correctly

// 4. Mixed script detection
// If text contains both Devanagari and Latin, use font stack:
// Devanagari ranges → Noto Sans Devanagari
// Latin ranges → Inter/Poppins
```

---

## Phases 18-20: Rendering + Output

### Phase 18: Unit Render

For each unit, render the Remotion composition to video:

```bash
npx remotion render studio/remotion/src/index.ts \
  UnitComposition \
  --props='{"specPath": "units/unit_001/composition_spec.json"}' \
  --output="units/unit_001/rendered.mp4" \
  --codec=h264 \
  --image-format=jpeg \
  --quality=85 \
  --concurrency=4 \
  --frames=0-4500
```

**Quality gate**: After render, verify:
- [ ] File exists and size > 0
- [ ] ffprobe confirms expected duration (within 1 frame)
- [ ] ffprobe confirms expected resolution
- [ ] No render errors in Remotion output
- [ ] Audio streams present (video + all SFX layers mixed)

### Phase 19: Global Composition

Build the master composition that stitches all unit renders:

1. **Sequence units** per `unit_order` from edit manifest
2. **Inter-unit transitions**: Different from within-unit transitions. Between topics → fade black (0.8s). Between related units → crossfade (0.5s). User can override.
3. **Global music**: If a single music track spans multiple units, apply here. Per-unit music crossfades at unit boundaries.
4. **Global effects**: Consistent film grain, color grade, vignette across all units (already baked per-unit, but verify consistency)
5. **Intro/outro**: If user specified, add title card and end screen

### Phase 20: Final Render + Metadata + Cleanup

1. Render master composition to final video
2. Generate YouTube metadata (title, description, chapters from unit boundaries, tags)
3. Generate thumbnails
4. Cleanup: remove tmp/, optionally remove analysis/vfx/ pre-processing outputs

**Output formats:**
- 16:9 long-form (1920×1080, 30fps)
- 9:16 long-form (1080×1920, 30fps) — uses crop keyframes from timeline
- 9:16 shorts (extracted key segments, < 60s each)

---

## Quality Gates

### Phase 14 (Composition)
- [ ] Every clip in the unit has at least one effect or is intentionally raw
- [ ] Every transition has a type and duration
- [ ] All typography text is non-empty and uses correct font for language
- [ ] All SFX have non-empty prompts with specific descriptors
- [ ] Music composition plan sections map to pacing map regions
- [ ] No two overlays overlap at the same position and time without z-ordering
- [ ] Coupled SFX references valid VFX IDs

### Phase 15 (Audio Generation)
- [ ] `FILE_VALID`: All generated SFX > 10KB, ffprobe confirms valid audio
- [ ] `NOT_SILENCE`: Peak amplitude > -40dB for each SFX file
- [ ] `DURATION_MATCH`: Duration within 0.5s of requested
- [ ] `MUSIC_INSTRUMENTAL`: Music contains no vocals (force_instrumental=true was used)
- [ ] `MUSIC_FILE_VALID`: Music file > 100KB for 30s, correct sample rate
- [ ] `COUPLING_INTACT`: Every coupled SFX has matching VFX ID in composition spec

### Phase 16 (Remotion Build)
- [ ] Remotion project compiles without errors
- [ ] All media paths in composition spec resolve to existing files
- [ ] Total frame count matches expected duration
- [ ] Typography renders correctly (test: render frame with Nepali text, verify non-empty)

### Phase 18 (Unit Render)
- [ ] Rendered video exists, duration matches spec
- [ ] Audio is present and audible
- [ ] No visual artifacts in spot-check (render 3 sample frames, verify non-black, non-corrupt)

### Phase 19 (Global)
- [ ] All units present in sequence
- [ ] Inter-unit transitions render cleanly
- [ ] Music crossfades at unit boundaries
- [ ] Total duration = sum of unit durations + transition durations

---

## Migration from Current Pipeline

### What changes:
- Phase 9: Extended output (editorial_beats, pacing_map, typography_candidates)
- Phases 13-20: Completely replaced (see above)
- Music: ElevenLabs Eleven Music replaces Lyria 2 / Lyria RealTime
- SFX: ElevenLabs SFX v2 (same provider, updated model)
- Output: Remotion renders video. No Blender VSE. No FCPXML.
- Studio: Extended with VFX panel, Remotion Player preview tab

### What stays:
- Phases 1-8: Unchanged (setup, scan, audio, ASR, VAD, scenes, frames, YOLO)
- Phase 9: Same Gemini Flash call, extended output schema
- Phase 10: Screen recording sync (unchanged)
- Phase 11: Narrative analysis + timeline + unit decomposition (unchanged)
- Phase 12: Studio session (unchanged, plus new VFX panel)
- Manifest schema: Extended, not replaced. All existing fields preserved.
- Style config: Extended with VFX defaults

### What's removed:
- `scripts/build_blender_project.py` — deprecated
- `scripts/export_fcpxml.py` — deprecated
- `references/blender-vse-api.md` — deprecated
- `references/nle-export-formats.md` — deprecated
- Lyria 2 / Lyria RealTime music generation
- All Blender-related code and references

---

## Style Config Extension

Add to `style_config.json`:

```json
{
  "vfx": {
    "film_grain": {
      "default_intensity": 0.15,
      "size": 1.5,
      "animated_speed": 24
    },
    "light_leaks": {
      "default_intensity": 0.3,
      "warmth": 0.7,
      "frequency": "on_transitions"
    },
    "color_grade": {
      "temperature_shift": 200,
      "tint_shift": 5,
      "saturation": 0.9,
      "contrast": 1.1,
      "shadows_hue": 240,
      "highlights_hue": 40
    },
    "vignette": {
      "amount": 0.25,
      "roundness": 0.8
    },
    "ken_burns": {
      "default_easing": "SINE",
      "default_zoom_factor": 1.3,
      "min_duration_frames": 30,
      "max_speed_px_per_sec": 200
    },
    "background_blur": {
      "default_amount": 8,
      "fade_frames": 15
    }
  },

  "typography": {
    "heading_font": "Poppins",
    "body_font": "Inter",
    "code_font": "JetBrains Mono",
    "nepali_font": "Noto Sans Devanagari",
    "impact_number": {
      "font": "Poppins",
      "weight": 700,
      "size_px": 180,
      "color": "#FF6B35",
      "animation": "scale_bounce_in",
      "spring": { "damping": 12, "mass": 1, "stiffness": 150 }
    },
    "label": {
      "font_primary": "Noto Sans Devanagari",
      "font_secondary": "Inter",
      "weight": 600,
      "size_primary_px": 48,
      "size_secondary_px": 28,
      "color": "#FFFFFF",
      "background": "rgba(26, 26, 46, 0.85)",
      "animation": "slide_up",
      "duration_frames": 10
    },
    "headline": {
      "font": "Noto Sans Devanagari",
      "weight": 700,
      "size_px": 72,
      "color": "#FFFFFF",
      "animation": "character_reveal",
      "stagger_frames": 2
    },
    "subtitle_emphasis": {
      "font": "Noto Sans Devanagari",
      "weight": 600,
      "size_px": 36,
      "color": "#F7C948",
      "animation": "typewriter",
      "sync_to_speech": true
    }
  },

  "audio": {
    "music_volume_db": -18.0,
    "music_duck_volume_db": -26.0,
    "music_duck_attack_seconds": 0.3,
    "music_duck_release_seconds": 0.8,
    "sfx_volume_db": -6.0,
    "ambient_volume_db": -28.0,
    "emphasis_volume_db": -8.0,
    "foley_volume_db": -10.0,
    "ui_volume_db": -12.0,
    "speech_target_lufs": -16.0
  },

  "transitions": {
    "default_within_unit": "cut",
    "default_between_units": "fade_black",
    "between_units_seconds": 0.8,
    "whip_pan_frames": 12,
    "dissolve_frames": 15,
    "mask_reveal_frames": 18,
    "glitch_frames": 8
  }
}
```

---

## Appendix: ElevenLabs API Reference

### Sound Effects v2
- **Endpoint**: `POST /v1/sound-generation`
- **Model**: `eleven_text_to_sound_v2`
- **Duration**: 0.5-30 seconds
- **Loop**: boolean (for ambient beds)
- **Prompt influence**: 0.0-1.0 (default 0.3)
- **Output**: `pcm_48000` (48kHz PCM WAV)
- **Rate limits**: Use exponential backoff (2s, 4s, 8s... up to 60s)
- **Env var**: `ELEVENLABS_API_KEY`

### Eleven Music
- **Endpoint**: `POST /v1/music`
- **Model**: `music_v1`
- **Duration**: 3s-5min (via `music_length_ms` or section durations)
- **Modes**: Simple prompt OR composition plan (mutually exclusive)
- **force_instrumental**: ALWAYS true
- **seed**: uint32 for reproducibility (composition plan only)
- **Output**: `pcm_48000` (48kHz PCM WAV)
- **Composition plan**: sections with positive/negative styles, durations

### Common Output Formats
`mp3_44100_128`, `pcm_48000`, `opus_48000_128`

For pipeline use: always `pcm_48000` (lossless, 48kHz, matches video audio).
