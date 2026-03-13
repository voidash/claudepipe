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

## Music via Google Lyria / Gemini

The `google.genai` package is installed. Use Gemini with audio output modality for music generation.

```python
from google import genai
from google.genai import types

client = genai.Client()

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Create a calm lo-fi hip-hop instrumental, 30 seconds, loop-friendly, minimal melody that won't compete with speech",
    config=types.GenerateContentConfig(
        response_modalities=["AUDIO"],
    ),
)

# Extract audio data from response
audio_data = response.candidates[0].content.parts[0].inline_data.data
mime_type = response.candidates[0].content.parts[0].inline_data.mime_type
```

### Prompt guidelines

- Specify style, mood, tempo, and approximate duration.
- Always include "loop-friendly" if the music will be looped under narration.
- Always include "non-competing with speech" or "instrumental, no vocals" to keep it under narration.
- Avoid requesting specific copyrighted artists or songs.

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

Apply ducking as volume keyframes on the music strip in Blender's VSE. Pre-compute keyframe times from VAD segments, padding the attack time before each speech start and the release time after each speech end. Overlapping speech segments should merge into a single ducked region.
