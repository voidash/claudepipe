# Gemini Flash Video Understanding

Reference for using Gemini 2.5 Flash as the vision analysis backend (Phase 9). Processes raw video files with audio natively — no frame extraction needed for descriptive analysis.

## API Flow

### 1. Upload video via File API

```python
from google import genai
import time

client = genai.Client()

video_file = client.files.upload(file="raw/clip_001.mp4")

# File API processes asynchronously — poll until ACTIVE
while not video_file.state or video_file.state.name != "ACTIVE":
    time.sleep(5)
    video_file = client.files.get(name=video_file.name)
```

Files are stored for **48 hours**, then auto-deleted.

**File size limits:**
- File API: 2 GB per file, 20 GB per project
- Inline base64: under 20 MB (not recommended for video)

### 2. Generate structured analysis

```python
from google.genai import types

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        video_file,
        """Analyze this video footage. Return JSON with this schema:
        {
          "segments": [{"start": float, "end": float, "description": str, "subjects": [str], "setting": str, "activity": "talking_head|demo|whiteboard|outdoor|b_roll|screen_recording", "quality_score": float 0-1, "quality_issues": [str], "text_visible": str, "interest_score": float 0-1}],
          "scene_boundaries": [float timestamps],
          "overall_summary": str
        }
        Segment by activity changes and scene boundaries. Include audio context (what is being said, tone, emphasis). Rate quality and interest honestly — dead air, repeated takes, and false starts get low scores."""
    ],
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        media_resolution="low"  # saves tokens, sufficient for descriptive analysis
    )
)
```

### 3. Video clipping (process segment only)

```python
types.Part(
    file_data=types.FileData(file_uri=video_file.uri),
    video_metadata=types.VideoMetadata(
        start_offset="120s",
        end_offset="600s"
    )
)
```

### 4. Custom frame rate

```python
video_metadata=types.VideoMetadata(fps=0.5)  # half the default 1fps
```

## Supported Formats

`video/mp4`, `video/mpeg`, `video/mov`, `video/avi`, `video/x-flv`, `video/webm`, `video/wmv`, `video/3gpp`

## Duration Limits (1M token context window)

| Resolution | Max Duration (video only) | Max Duration (video + audio) |
|---|---|---|
| Default | ~1 hour | ~45 minutes |
| Low (`media_resolution="low"`) | ~3 hours | ~2 hours |

For 8-minute footage clips, this is never a constraint.

## Token Cost (8-minute video)

| Mode | Video Tokens | Audio Tokens | Total | Cost (2.5 Flash) |
|---|---|---|---|---|
| Default res + audio | ~123,840 | ~15,360 | ~139,200 | ~$0.06 |
| Low res + audio | ~31,680 | ~15,360 | ~47,040 | ~$0.03 |
| 50 extracted frames (no audio) | ~12,900 | 0 | ~12,900 | ~$0.009 |

Low resolution is the default for this pipeline — descriptive analysis doesn't need pixel-level detail. YOLO handles fine-grained spatial analysis on extracted frames separately.

## What Gemini Flash Gives vs Doesn't

### Gives
- Joint audio+visual understanding (hears speech while seeing the scene)
- Temporal context (sees motion, transitions, pacing)
- Second-level timestamped segment descriptions
- Activity classification with audio cues
- Scene boundary detection (supplements OpenCV Phase 6)
- Content summary across the full clip

### Does NOT give
- Word-level timestamps (use Chirp 2)
- Object tracking across frames (use YOLO)
- Frame-accurate timestamps (1-second granularity only)
- Reliable Nepali audio transcription (unconfirmed — use Chirp 2 for `ne-NP`)
- Speaker diarization (no support)
- Per-frame bounding boxes for crop keyframes (use YOLO)

## Nepali Language Note

Gemini's multimodal audio understanding may handle Nepali speech for *descriptive* purposes (e.g., "the speaker is explaining a technical concept in Nepali"), but there is no official confirmation of reliable Nepali transcription. Do NOT use Gemini as an ASR replacement for Nepali content. Continue using Chirp 2 (`ne-NP`) for word-level transcripts.

## Error Handling

- File upload can fail for corrupt/unsupported files — always check `video_file.state` before calling `generate_content`
- If the File API returns `FAILED`, fall back to Claude Vision backend
- Gemini rate limits: respect 429 responses with exponential backoff (same as ElevenLabs — 2s start, double to 60s max, 5 retries)
- Structured JSON output (`response_mime_type="application/json"`) occasionally returns malformed JSON — validate and retry once before falling back
