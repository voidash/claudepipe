# YouTube Clip Scout Pipeline

Low-cost pipeline for identifying and extracting specific moments from YouTube videos without downloading full videos.

## Problem

Downloading full videos to find 10-second clips wastes bandwidth and time. Many Nepali videos have no auto-subtitles, so transcript-only analysis misses the best footage. We need a cheap screening step before committing to full downloads.

## yt-dlp Fix (March 2026)

YouTube requires JS challenge solving. yt-dlp needs a JavaScript runtime. Without it, only storyboard formats are returned and "n challenge solving failed" appears.

**Required flags on every yt-dlp command:**
```bash
--js-runtimes node --remote-components ejs:github
```

Node must be installed (`/opt/homebrew/bin/node` on macOS). The `ejs:github` remote component downloads the challenge solver script (v0.8.0+) automatically and caches it.

## Pipeline Overview

```
Search (free) → Scout (5MB/video) → Analyze (free/local) → Extract (2-5MB/clip)
```

### Step 1: Search — Find candidate videos

```bash
yt-dlp --js-runtimes node --remote-components ejs:github \
  --dump-json --flat-playlist "ytsearch15:{query}" 2>/dev/null
```

Run both English and Nepali queries. Extract: video_id, title, channel, duration, view_count. Filter by relevance.

### Step 2: Scout — Download audio + storyboard sprites

For each candidate (costs ~5MB total per video, vs 200-500MB for full video):

```bash
# Audio only (2-5MB for a 10min video)
yt-dlp --js-runtimes node --remote-components ejs:github \
  -f bestaudio -x --audio-format wav --audio-quality 5 \
  -o "/tmp/scout/%(id)s.%(ext)s" URL

# Storyboard sprites (sprite sheets of frames at regular intervals)
# sb0 = lowest res, sb2 = medium, sb3 = highest
yt-dlp --js-runtimes node --remote-components ejs:github \
  -f sb2 -o "/tmp/scout/%(id)s_storyboard.%(ext)s" URL

# Metadata
yt-dlp --js-runtimes node --remote-components ejs:github \
  --dump-json --skip-download URL > /tmp/scout/VIDEO_ID.json
```

### Step 3: Analyze — Transcribe + visual timeline

**Transcription (local, free) — use MLX Whisper on Apple Silicon:**
```python
# MLX Whisper (Apple Silicon optimized — 5-10x faster than regular Whisper)
import mlx_whisper

result = mlx_whisper.transcribe(
    "/tmp/scout/VIDEO_ID.wav",
    path_or_hf_repo="mlx-community/whisper-small-mlx",
    language="ne",
    word_timestamps=True,
)
# result["segments"] has start/end per segment
# result["segments"][n]["words"] has per-word timestamps

import json
with open("/tmp/scout/VIDEO_ID/transcript.json", "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
```

Available MLX models (all from `mlx-community/` on HuggingFace):
- `whisper-tiny-mlx` — fastest, least accurate
- `whisper-small-mlx` — good balance for Nepali
- `whisper-medium-mlx` — better accuracy, still fast on M-series
- `whisper-large-v3-mlx` — best accuracy, ~2x real-time on M1 Pro

**Fallback: regular Whisper CLI** (if mlx_whisper unavailable):
```bash
whisper /tmp/scout/VIDEO_ID.wav --model small --language ne \
  --output_format json --output_dir /tmp/scout/
```

**Fallback: Chirp 2** (for production-quality Nepali transcription):
Split to 52s chunks, send to us-central1, merge results.

MLX Whisper output includes word-level timestamps in JSON format. This is better than YouTube auto-subs for Nepali because:
- Works on videos with no auto-subs
- More accurate for Nepali
- Provides word-level timing, not just sentence-level
- Runs entirely local — zero API cost

**Visual timeline — storyboard sprite analysis:**

Storyboard sprites are JPEG sprite sheets (typically 5x5 or 10x10 grids). Claude reads the full sprite sheet as one image and gets a visual timeline at a glance. No need to split into individual frames for the screening step.

Alternatively, split with ffmpeg:
```bash
# If sprite is 5 columns × N rows, each cell is W/5 × H/N
ffmpeg -i storyboard.jpg -vf "crop=iw/5:ih/5:0:0" frame_0.jpg
```

### Step 4: Identify moments — Claude reads both signals

Claude reads:
- The storyboard sprite sheet (visual timeline)
- The Whisper transcript JSON (word-level timestamps)
- Video metadata (title, description, chapters)

Combined analysis identifies specific moments:
```json
{
  "video_id": "abc123",
  "moments": [
    {
      "start": "2:30",
      "end": "2:42",
      "description": "Crowd marching at Singha Durbar with flags",
      "evidence": "Frame 14 in storyboard shows crowd + transcript says 'सिंहदरबार अगाडि' at 2:35",
      "confidence": "high"
    }
  ]
}
```

### Step 5: Surgical extraction — Only confirmed moments

```bash
yt-dlp --js-runtimes node --remote-components ejs:github \
  -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]" \
  --download-sections "*2:30-2:42" \
  -o "clips/protest_singhadurbar.%(ext)s" URL
```

### Step 6: Post-download visual verification

After downloading each clip, extract frames and verify visually:

```bash
# Extract 3 frames: start, middle, end
ffmpeg -i clip.mkv -vf "select='eq(n,0)+eq(n,45)+eq(n,90)'" -vsync vfr /tmp/verify_%d.jpg
```

Claude reads the frames to confirm the clip actually shows what was expected. If wrong, adjust timestamps and retry.

## Cost comparison

| Approach | Download per video | Analysis cost |
|----------|-------------------|---------------|
| Full video + hope | 200-500MB | Wasted if wrong |
| Transcript only | ~1MB subs | Misses no-sub videos |
| **Scout pipeline** | **~5MB audio + sprite** | **Free local + Claude vision** |
| Final clip extraction | 2-5MB per confirmed clip | Already verified |

The scout pipeline screens 50 videos for the cost of downloading 1 full video.

## Fallback when no transcript AND no storyboard

Some very short or very new videos may lack both. In that case:
1. Download the full video at lowest quality: `-f worst`
2. Extract frames at 2-second intervals: `ffmpeg -i video.mp4 -vf fps=0.5 frames_%d.jpg`
3. Claude reads frames to identify moments
4. Re-download the specific section at full quality

## Integration with footage pipeline

This pipeline fits into **Phase 11c (Asset Acquisition)** for video clip assets. The clip_manifest.json output follows the same schema as the image asset manifest:

```json
{
  "id": "clip_balen_oath",
  "type": "video_segment",
  "source_url": "https://youtube.com/watch?v=...",
  "source_channel": "...",
  "file": "clips/ministers/balen_oath_moment.mkv",
  "start": "1:23",
  "end": "1:35",
  "duration_seconds": 12,
  "resolution": "1920x1080",
  "description": "Balen reading oath at Sheetal Niwas",
  "transcript_excerpt": "म बालेन्द्र शाह शपथ लिन्छु...",
  "needed_by": ["cold-open", "balen"],
  "status": "ready"
}
```
