# Music Generation: Sonauto API

## API Reference

**Base URL:** `https://api.sonauto.ai/v1`
**Auth:** `Authorization: Bearer {SONAUTO_API_KEY}`
**Credits:** 100 per track (~1:35), 150 for 2 tracks. Free tier: 1,500 credits (15 songs).

### Generate Track (v2 — use this for fixed-length beds)

```bash
curl -X POST https://api.sonauto.ai/v1/generations/v2 \
  -H "Authorization: Bearer $SONAUTO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Minimal electronic documentary underscore, subtle synth pad, 90 BPM",
    "tags": ["documentary", "ambient", "electronic", "underscore"],
    "instrumental": true,
    "bpm": 90,
    "output_format": "mp3",
    "num_songs": 1,
    "prompt_strength": 0.7
  }'
```

Returns `{"task_id": "..."}`. Poll status, then download.

### Check Status

```bash
curl https://api.sonauto.ai/v1/generations/status/{task_id} \
  -H "Authorization: Bearer $SONAUTO_API_KEY"
```

### Download Track

```bash
curl https://api.sonauto.ai/v1/generations/{task_id} \
  -H "Authorization: Bearer $SONAUTO_API_KEY" \
  -o track.mp3
```

### v3 (variable length, 2-4 min)

Same endpoint but `/generations/v3`. No `bpm`, `seed`, `num_songs` params. Supports streaming.

### Extend Track

```bash
curl -X POST https://api.sonauto.ai/v1/generations/v2/extend \
  -H "Authorization: Bearer $SONAUTO_API_KEY" \
  -F "audio_file=@track.mp3" \
  -F "prompt=continue the same mood and style" \
  -F "instrumental=true"
```

## Parameters

| Param | Type | Notes |
|-------|------|-------|
| `prompt` | string | Text description of desired music |
| `tags` | string[] | Genre/mood tags |
| `instrumental` | bool | **Always true for documentary** — no vocals |
| `bpm` | int/string | Specific tempo or "auto" (v2 only) |
| `prompt_strength` | float | 0.5-0.9 recommended. Higher = more literal |
| `output_format` | string | mp3, wav, flac, ogg, m4a |
| `num_songs` | int | 1 or 2 per request (v2 only) |

## Documentary Music Prompts (JH-style)

Based on Johnny Harris style analysis — his composer Tom Fox creates custom scores through Chromatic Studio. These prompts replicate the mood palette:

| Mood | Prompt | Tags | BPM |
|------|--------|------|-----|
| Educational bed | "Minimal electronic documentary underscore, subtle synth pad, gentle rhythmic pulse, not distracting, background bed" | documentary, ambient, electronic, minimal | 90 |
| Epic map reveal | "Cinematic orchestral swell, building brass and strings, epic discovery, exploration documentary, wide open" | cinematic, orchestral, epic, documentary | 110 |
| Tense political | "Dark ambient tension, sparse percussion, low drone, political documentary, building suspense, uneasy" | dark, ambient, tension, political, suspense | 85 |
| Somber reflective | "Solo piano with ambient reverb, slow reflective, space between notes, documentary grief, contemplative" | piano, ambient, reflective, somber | 70 |
| Warm hopeful | "Warm acoustic guitar with light percussion, optimistic but measured, documentary hope, gentle forward motion" | acoustic, warm, hopeful, documentary | 100 |
| Dark ominous | "Deep bass drone, industrial texture, slow percussive hits, authoritarian theme, menacing undercurrent" | dark, industrial, ominous, drone | 75 |
| Contemplative closing | "Minimal piano with ambient texture, long sustain, ending credits feel, gentle resolution, slowly fading" | piano, ambient, contemplative, closing | 65 |

## Usage in Pipeline

1. **Phase 15 (Music):** Generate 7 mood tracks using prompts above
2. **Extend** tracks to 3-4 minutes each using `/extend` endpoint
3. **Demucs** to separate any residual vocal artifacts (force instrumental should prevent this)
4. **Remotion MusicLayer:** Places tracks at script-appropriate moments with:
   - Ducking to 20-30% under speech
   - Drops to 0% at [BEAT] markers (silence before key statements)
   - Swells to 100% during map montages
   - Crossfades between mood tracks at act transitions

## Quality Gate

- [ ] `NOT_SPEECH`: No vocals detected (instrumental flag was set)
- [ ] `MOOD_MATCH`: Track mood matches the prompt intent
- [ ] `BPM_MATCH`: Tempo approximately matches requested BPM
- [ ] `LOOP_CLEAN`: Track can loop without jarring discontinuity
- [ ] `MIX_COMPATIBLE`: Volume level compatible with speech ducking (not too loud/quiet)
