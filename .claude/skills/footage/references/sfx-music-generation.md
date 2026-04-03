# SFX and Music Generation

Reference for generating sound effects and background music within the footage pipeline.

## SFX via ElevenLabs

The `elevenlabs` package is installed. Authentication uses the `ELEVEN_API_KEY` environment variable automatically.

```python
from elevenlabs import ElevenLabs

client = ElevenLabs()  # picks up ELEVEN_API_KEY from env

result = client.text_to_sound_effects.convert(
    text="heavy wooden door creaking open slowly in a quiet stone hallway",
    duration_seconds=3.0,
)
# result is a byte generator — consume it into bytes
audio_bytes = b"".join(result)
```

### Prompt guidelines

- Be specific about the sound's character: material, environment, intensity, speed.
- Include spatial context when relevant ("close mic", "distant", "reverberant room").
- Specify duration intent in the prompt text as well as the parameter — the model responds to both.
- Bad prompt: "door sound". Good prompt: "heavy wooden door creaking open slowly in a quiet stone hallway".

### Rate limits

ElevenLabs enforces rate limits. On receiving a 429 response, apply exponential backoff starting at 2 seconds, doubling up to a max of 60 seconds. Never retry more than 5 times for a single request.

## Music Generation

**WARNING: Gemini `response_modalities=["AUDIO"]` is TTS, NOT music generation.** It produces speech narration, not instrumental tracks. This was confirmed 2026-03-13. To generate music, use the Lyria API (separate system).

### Lyria 2 on Vertex AI (recommended)

GA API — no waitlist. Generates ~30-second instrumental WAV at 48kHz. Pricing: $0.06 per 30s clip.

```python
from google.cloud import aiplatform
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Value
import base64

PROJECT = "agentshakti"
LOCATION = "us-central1"

client = aiplatform.gapic.PredictionServiceClient(
    client_options={"api_endpoint": f"{LOCATION}-aiplatform.googleapis.com"}
)
endpoint = f"projects/{PROJECT}/locations/{LOCATION}/publishers/google/models/lyria-002"

instance = json_format.ParseDict({
    "prompt": "upbeat lo-fi hip hop beat, chill study music, warm bass, soft drums, no vocals",
    "negative_prompt": "vocals, singing, speech, harsh, aggressive"
}, Value())

response = client.predict(endpoint=endpoint, instances=[instance])

# Response format varies — try extraction paths in order:
prediction = response.predictions[0]
audio_b64 = None
try:
    audio_b64 = prediction["generated_music"][0]["audio"]
except (KeyError, IndexError, TypeError):
    try:
        audio_b64 = prediction["generated_music"][0]["bytesBase64Encoded"]
    except (KeyError, IndexError, TypeError):
        audio_b64 = prediction["bytesBase64Encoded"]

wav_bytes = base64.b64decode(audio_b64)
with open("music/track_001.wav", "wb") as f:
    f.write(wav_bytes)
```

**Constraints:**
- ~30 seconds per generation. For longer tracks, generate multiple segments with consistent prompts and crossfade at boundaries
- Prompts must be **US English** (en-us)
- `seed` (uint32) for reproducibility — same seed + same prompt = deterministic output
- `seed` and `sample_count` may be mutually exclusive per docs
- Latency: 10-20 seconds per generation
- Output: base64-encoded WAV, 48kHz, instrumental only, SynthID watermarked

**Prompt guidelines** (7 components):
1. Genre & style — primary musical category
2. Mood & emotion — desired feeling
3. Instrumentation — specific instruments
4. Tempo & rhythm — pace, BPM, rhythmic character
5. Arrangement/structure (optional) — progression, layering
6. Soundscape/ambiance (optional) — background sounds
7. Production quality (optional) — audio fidelity
- Use `negative_prompt` to exclude vocals/speech

### Lyria RealTime via Gemini API (experimental — streaming)

WebSocket streaming for longer continuous tracks. Model: `models/lyria-realtime-exp`. Uses `google-genai` SDK with `api_version='v1alpha'`. Output: raw PCM16 at 48kHz stereo.

```python
from google import genai

client = genai.Client(api_key="GEMINI_API_KEY", api_version="v1alpha")

async with client.aio.live.music.connect(model="models/lyria-realtime-exp") as session:
    await session.set_weighted_prompts([
        {"text": "ambient electronic, soft pads, no drums", "weight": 1.0}
    ])
    await session.set_music_generation_config({
        "bpm": 90,
        "temperature": 1.1,
        "guidance": 4.0
    })
    await session.play()
    # Streams PCM16 audio chunks continuously
    # Capture to WAV file as needed
```

**Configuration parameters:** `guidance` (0-6, default 4), `bpm` (60-200), `density` (0-1), `brightness` (0-1), `temperature` (0-3, default 1.1), `top_k` (1-1000, default 40), `scale` (C major through B major), `mute_bass`, `mute_drums`, `only_bass_and_drums`, `music_generation_mode` (QUALITY/DIVERSITY/VOCALIZATION).

Supports up to 50 weighted prompt layers. Playback controls: `play()`, `pause()`, `stop()`, `reset_context()` (required before changing bpm/scale).

Works with a free AI Studio API key. Good for generating longer ambient tracks without stitching.

### Other music sources

1. **User provides a track** — royalty-free from YouTube Audio Library, Artlist, Epidemic Sound, etc. Pipeline computes ducking keyframes and integrates.
2. **Mubert API** — GA REST API ($49-199/mo). Generates tracks up to 25 min. 200+ moods/genres. Royalty-free. Only use if Lyria quality is insufficient.
3. **Skip music in pipeline** — user adds music in NLE. Ducking keyframe data is still written to manifest for reference.

Note: Suno and Udio have **no official public APIs** — third-party wrappers exist but are legally gray. Avoid for automated pipelines.

### Music generation checklist

Before marking music generation complete:
- [ ] Verify generated files are actual music (not speech/narration) — play-test
- [ ] ffprobe confirms valid audio codec, sample rate, duration
- [ ] File size is reasonable (>100KB for 30s WAV)
- [ ] No clipping or distortion artifacts
- [ ] Style matches user-approved brief
- [ ] For multi-segment tracks: crossfades between segments sound natural
- [ ] Ducking keyframes computed from VAD data and written to manifest

### If music is provided externally

```python
# Compute ducking keyframes from VAD/transcript data and write to manifest
# See "Music Ducking" section below for parameters
# Store in manifest: music.tracks[0].ducking.keyframes
```

## SFX Placement Logic

### Auto-place (high confidence)

These can be placed without user confirmation:

- Scene transitions (whooshes, risers)
- Text or graphic appearances (subtle pops, swooshes)
- Explicit scene changes detected in the manifest

### Semi-auto (suggest to user)

Suggest placement but require approval:

- Speech pauses longer than 0.5 seconds
- Pitch emphasis changes in narration
- Topic transitions within a scene

### Never auto-place

Always require explicit user instruction:

- Comedic timing hits
- Object interaction sounds (foley)
- Emotional beat punctuation (stingers, swells)

## Music Ducking

Background music must duck under speech. Derive ducking keyframes from VAD (voice activity detection) data in the manifest.

| Parameter | Value |
|-----------|-------|
| Attack time | 0.3 seconds (fade music down before speech) |
| Release time | 0.8 seconds (fade music back up after speech) |
| Speech-active volume | -26 dB |
| Non-speech volume | -18 dB |

Apply ducking as volume keyframes on the music strip in Blender's VSE. Pre-compute keyframe times from VAD segments, padding the attack time before each speech start and the release time after each speech end. Overlapping speech segments should merge into a single ducked region (gap threshold = attack + release = 1.1s).

**FCPXML caveat:** FCPXML `<keyframe>` volume values use **linear gain** (0.0 = silence, 1.0 = unity), NOT dB. Convert: `gain = 10^(dB/20)` → speech-active = 0.05, non-speech = 0.126. However, **DaVinci Resolve ignores FCPXML volume keyframes on import** — this is a known longstanding bug. Ducking keyframes are still written to FCPXML for Final Cut Pro (which respects them) and stored in the manifest for manual application in DaVinci.

## ElevenLabs API Key

The env var name is `ELEVENLABS_API_KEY` (not `ELEVEN_API_KEY`). Store in the project's `.env` file. The key may have limited permissions — SFX generation works even without `user_read` scope.

## SFX Verification

After generating SFX, ALWAYS verify:
- File size is reasonable (>10KB for a 1s sound)
- Play each file to confirm it's the right type of sound (not silence, not garbage)
- Duration matches what was requested
- Files are valid audio (ffprobe returns clean metadata)
