# Short-Form Content Extraction

Reference for extracting short-form (vertical) content from long-form footage.

## Segment Selection

Claude reads the project manifest and suggests **3-5 self-contained story segments** suitable for shorts. Each suggestion includes the segment's time range, a one-line summary, and a confidence score.

### Criteria for good shorts

- **Single clear topic**: the segment must be understandable without context from the rest of the video.
- **Emotional hook**: opens with a surprising fact, bold claim, question, or visual moment.
- **Under 60 seconds**: target 30-50 seconds. Absolute maximum is 60 seconds.
- **Strong opening**: the first 2 seconds must hook the viewer. No slow intros, no "so today we're going to..."
- **Clean boundaries**: the segment should start and end at natural speech boundaries, not mid-sentence.

## Process

1. **Claude reads the manifest** — analyzes transcription segments, scene boundaries, and topic markers.
2. **Identifies candidate segments** — selects 3-5 candidates meeting the criteria above. Presents them to the user with reasoning.
3. **User selects segments** — user approves, rejects, or modifies the selections.
4. **Claude writes condensed narration** — for each approved segment, writes a tight narration script optimized for vertical format. This may rephrase or tighten the original speech.
5. **User records voiceover** — user records the condensed narration (or approves using the original audio if it's tight enough).
6. **Claude builds 9:16 Blender project** — assembles the short in Blender's VSE with dynamic crop, text overlays, and transitions.

## Format

- Always **9:16** (1080x1920).
- Each short gets its own `.blend` file in the `blender/` directory, named `short_01.blend`, `short_02.blend`, etc.
- Dynamic crop is critical for shorts. Crop behavior should be more aggressive and faster than long-form: tighter framing on the speaker's face, faster pan to follow gestures or screen content, and minimal dead space.

## Manifest Integration

The manifest tracks shorts in the `outputs.shorts` array:

```json
{
  "outputs": {
    "shorts": [
      {
        "id": "short_01",
        "source_range": { "start": 124.5, "end": 168.2 },
        "blend_file": "blender/short_01.blend",
        "narration_script": "...",
        "status": "draft"
      }
    ]
  }
}
```

Each entry records the source time range, the path to its `.blend` file, the narration script, and a status field (`draft`, `recorded`, `assembled`, `reviewed`, `exported`).
