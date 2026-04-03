# Footage Manifest Schema (`footage_manifest.json`)

The manifest is the **single source of truth** for the entire pipeline. Every script reads from and writes to this file. It lives at `{project_root}/footage_manifest.json`.

All paths inside the manifest are **relative to project_root** unless marked as `absolute_path`.

## Top-Level Structure

```json
{
  "version": "1.0.0",
  "project": { ... },
  "clips": [ ... ],
  "timeline": { ... },
  "units": [ ... ],
  "sfx": [ ... ],
  "music": { ... },
  "animations": [ ... ],
  "thumbnails": [ ... ],
  "outputs": { ... },
  "youtube": { ... },
  "pipeline_state": { ... }
}
```

## `project`

```json
{
  "id": "footage_project_20260313",
  "created": "2026-03-13T14:30:00Z",
  "root_dir": "/absolute/path/to/footage_project_20260313",
  "hint": "User's text description of the footage/intent",
  "source_files": ["/absolute/path/to/original1.mp4", "/absolute/path/to/original2.mp4"]
}
```

## `clips[]`

Each element in the clips array represents one source video file.

```json
{
  "id": "clip_001",
  "source_path": "/absolute/path/to/original.mp4",
  "symlink_path": "raw/clip_001.mp4",
  "type": "camera | screen_recording",
  "classification_confidence": 0.95,

  "metadata": {
    "duration_seconds": 120.5,
    "width": 1920,
    "height": 1080,
    "fps": 30.0,
    "fps_rational": "30000/1001",
    "codec_video": "h264",
    "codec_audio": "aac",
    "audio_channels": 2,
    "audio_sample_rate": 48000,
    "bit_rate_bps": 20000000,
    "creation_time": "2026-03-13T10:00:00Z",
    "camera_model": "GoPro HERO12 Black",
    "rotation": 0,
    "file_size_bytes": 123456789,
    "has_audio": true
  },

  "audio": {
    "extracted_path": "audio/clip_001.wav",
    "denoised_path": "audio/denoised/clip_001.wav",
    "noise_removal_applied": true,
    "noise_removal_engine": "deepfilternet | none",
    "sample_rate": 16000,
    "duration_seconds": 120.5
  },

  "transcript": {
    "path": "analysis/transcripts/clip_001.json",
    "engine": "chirp2 | whisper",
    "segments": [
      {
        "id": "tseg_001",
        "start": 0.0,
        "end": 2.5,
        "text": "यो video मा हामी discuss गर्छौं...",
        "language": "ne",
        "confidence": 0.92,
        "words": [
          {
            "word": "यो",
            "start": 0.0,
            "end": 0.15,
            "confidence": 0.95
          }
        ]
      }
    ]
  },

  "vad": {
    "path": "analysis/vad/clip_001.json",
    "engine": "silero",
    "speech_segments": [
      {"start": 0.0, "end": 2.5, "confidence": 0.98}
    ],
    "silence_segments": [
      {"start": 2.5, "end": 3.2, "duration": 0.7}
    ],
    "speech_ratio": 0.78
  },

  "pitch": {
    "path": "analysis/pitch/clip_001.json",
    "mean_hz": 165.0,
    "std_hz": 30.0,
    "emphasis_points": [
      {
        "time": 1.2,
        "type": "rise | fall | peak",
        "magnitude": 0.8,
        "hz": 220.0
      }
    ]
  },

  "scenes": {
    "path": "analysis/scenes/clip_001.json",
    "boundaries": [
      {
        "time": 15.3,
        "type": "cut | fade | dissolve | gradual",
        "confidence": 0.95,
        "frame_before": "frames/clip_001/scene_boundary_15.3_before.jpg",
        "frame_after": "frames/clip_001/scene_boundary_15.3_after.jpg"
      }
    ]
  },

  "frames": {
    "dir": "frames/clip_001/",
    "count": 45,
    "extracted": [
      {
        "path": "frames/clip_001/frame_000001.jpg",
        "time": 0.0,
        "reason": "scene_start | keyframe | speech_emphasis | silence_boundary | periodic | scene_boundary"
      }
    ]
  },

  "yolo": {
    "path": "analysis/yolo/clip_001.json",
    "model": "yolo11x.pt",
    "detections_by_frame": {
      "frames/clip_001/frame_000001.jpg": [
        {
          "class": "person",
          "class_id": 0,
          "confidence": 0.95,
          "bbox_xyxy": [100, 50, 500, 900],
          "bbox_xywh": [300, 475, 400, 850],
          "pose": {
            "keypoints": [[x, y, conf], ...],
            "facing": "camera | left | right | away"
          }
        }
      ]
    },
    "tracking_summary": {
      "primary_subject_bbox_median": [200, 100, 600, 900],
      "subject_movement_range": {"x_min": 150, "x_max": 650, "y_min": 80, "y_max": 920}
    }
  },

  "vision": {
    "path": "analysis/vision/clip_001.json",
    "analyses": [
      {
        "frame_path": "frames/clip_001/frame_000001.jpg",
        "time": 0.0,
        "description": "Person sitting at desk talking to camera, laptop visible, whiteboard behind",
        "subjects": ["person_talking_to_camera", "laptop", "whiteboard"],
        "setting": "indoor_office",
        "activity": "talking_head | demo | whiteboard | outdoor | b_roll",
        "quality_score": 0.85,
        "quality_issues": [],
        "text_visible": "some text on whiteboard",
        "interest_score": 0.8,
        "suggested_crop_9_16": {
          "x": 400,
          "y": 0,
          "w": 607,
          "h": 1080,
          "reason": "center on speaker face"
        }
      }
    ]
  },

  "screen_sync": null
}
```

### `screen_sync` (when non-null)

```json
{
  "synced_to_clip": "clip_002",
  "offset_seconds": 1.234,
  "correlation_score": 0.92,
  "layout": "pip | split | switch | side_by_side",
  "layout_params": {
    "pip_position": "top_right | top_left | bottom_right | bottom_left",
    "pip_scale": 0.25,
    "switch_timestamps": [10.0, 25.0, 40.0]
  }
}
```

## `timeline` — Universal Multi-Track Format

The global timeline is the **single representation** that all exporters (FCPXML, Blender, Remotion) read from. It is multi-track: main video, overlays, SFX, music. Clips on the timeline are *references* to source clips — a source clip can appear multiple times (if split).

```json
{
  "fps": 30,
  "resolution": {"w": 1920, "h": 1080},
  "total_duration_seconds": 600.0,
  "tracks": [
    {
      "id": "main",
      "type": "video",
      "clips": [
        {
          "id": "tc_001",
          "source_clip_id": "clip_003",
          "in_point": 5.0,
          "out_point": 23.5,
          "trim": {
            "in": 5.0,
            "out": 23.5,
            "original_in": 0.0,
            "original_out": 45.0
          },
          "deleted_ranges": [
            {"start": 12.0, "end": 15.0, "reason": "dead air"}
          ],
          "timeline_start": 0.0,
          "timeline_end": 15.5,
          "speed": 1.0,
          "volume": 1.0,
          "volume_keyframes": [
            {"time": 0.0, "value": 1.0, "interp": "linear"}
          ],
          "transform": {
            "x": 0.0, "y": 0.0,
            "scale": 1.0, "rotation": 0.0
          },
          "crop_9_16": {
            "keyframes": [
              {
                "time": 0.0,
                "x": 400, "y": 0, "w": 608, "h": 1080,
                "easing": "BEZIER"
              }
            ]
          },
          "interest_score": 0.85,
          "tags": ["intro", "talking_head"],
          "unit_id": "unit_001_intro"
        }
      ]
    },
    {
      "id": "overlay",
      "type": "video",
      "clips": [
        {
          "id": "tc_overlay_001",
          "source_clip_id": "anim_001",
          "in_point": 0.0,
          "out_point": 8.0,
          "trim": {"in": 0.0, "out": 8.0, "original_in": 0.0, "original_out": 8.0},
          "deleted_ranges": [],
          "timeline_start": 23.5,
          "timeline_end": 31.5,
          "transform": {"x": 0.0, "y": 0.0, "scale": 1.0, "rotation": 0.0},
          "unit_id": "unit_002_hooks"
        }
      ]
    },
    {
      "id": "sfx",
      "type": "audio",
      "clips": [
        {
          "id": "tc_sfx_001",
          "source_clip_id": "sfx_001",
          "in_point": 0.0,
          "out_point": 1.0,
          "timeline_start": 15.3,
          "timeline_end": 16.3,
          "volume": 0.5,
          "unit_id": "unit_001_intro"
        }
      ]
    },
    {
      "id": "music",
      "type": "audio",
      "clips": [
        {
          "id": "tc_music_001",
          "source_clip_id": "music_001",
          "in_point": 0.0,
          "out_point": 60.0,
          "timeline_start": 0.0,
          "timeline_end": 60.0,
          "volume_keyframes": [
            {"time": 0.0, "value": 0.126, "interp": "linear"},
            {"time": 5.0, "value": 0.05, "interp": "ease", "reason": "speech_start"},
            {"time": 35.0, "value": 0.126, "interp": "ease", "reason": "speech_end"}
          ],
          "loop": true,
          "fade_in_seconds": 2.0,
          "fade_out_seconds": 3.0
        }
      ]
    }
  ],
  "transitions": [
    {
      "id": "tr_001",
      "from_clip": "tc_001",
      "to_clip": "tc_002",
      "type": "crossfade",
      "duration_seconds": 0.5
    }
  ],
  "unit_groups": [
    {
      "id": "unit_001_intro",
      "name": "Channel Intro",
      "timeline_range": {"start": 0.0, "end": 15.5},
      "clip_ids": ["tc_001"],
      "status": "approved",
      "needs_animation": false
    }
  ]
}
```

**Clip on timeline vs source clip:** `clips[]` (top-level) are source clips with analysis data. `timeline.tracks[].clips[]` are timeline references that point to source clips via `source_clip_id`. This separation means: source analysis is done once, timeline references can be trimmed/split/reordered independently.

**Trim enforcement:** The `trim` field on each timeline clip defines the valid range. Exporters MUST clamp to this range. `deleted_ranges` are gaps within the trim range that the exporter skips. Phase 18 validates that no clip reference violates these constraints.

**Exporter mapping:**
- **FCPXML:** tracks → lanes (`main` = spine, `overlay` = lane 1, `sfx` = lane -1, `music` = separate audio), clips → `<asset-clip>`, transitions → `<transition>` elements
- **Blender VSE:** tracks → channels, clips → strips, transitions → crossfade effects
- **Remotion:** tracks → `<AbsoluteFill>` layers, clips → `<Sequence>` + `<OffthreadVideo>`, transitions → `<TransitionSeries>`

**Crop math for 9:16:**
- Source is 16:9 (e.g., 1920x1080)
- Target aspect = 9/16
- Crop width = height * 9/16 = 1080 * 9/16 = 607.5 → 608 (round to even)
- Crop height = source height (1080)
- x ranges from 0 to (1920 - 608) = 1312
- Keyframes animate x position; easing is NEVER "LINEAR"

## `sfx[]`

```json
{
  "id": "sfx_001",
  "description": "whoosh transition sound",
  "prompt": "quick whoosh swoosh transition sound effect",
  "duration_seconds": 1.0,
  "placement": {
    "type": "between_segments | within_segment | at_time",
    "after_segment": "seg_001",
    "before_segment": "seg_003",
    "absolute_time": null,
    "time_offset_seconds": -0.2
  },
  "generated_path": "sfx/sfx_001.wav",
  "auto_confidence": "high | medium | low",
  "auto_reason": "scene_change | transition | emphasis | pause",
  "approved": false,
  "volume_db": -6.0
}
```

## `music`

```json
{
  "tracks": [
    {
      "id": "music_001",
      "style_prompt": "chill lo-fi hip hop background music, subtle and unobtrusive",
      "generated_path": "music/music_001.wav",
      "duration_seconds": 60.0,
      "loop": true,
      "ducking_keyframes": [
        {"time": 0.0, "volume_db": -18.0},
        {"time": 5.0, "volume_db": -24.0, "reason": "speech_start"},
        {"time": 35.0, "volume_db": -18.0, "reason": "speech_end"}
      ],
      "placement": {
        "start_time": 0.0,
        "end_time": null,
        "fade_in_seconds": 2.0,
        "fade_out_seconds": 3.0
      },
      "approved": false
    }
  ]
}
```

## `animations[]`

```json
{
  "id": "anim_001",
  "type": "manim | remotion",
  "description": "Diagram showing CPU pipeline stages",
  "source_code_path": "animations/anim_001.py",
  "rendered_path": "animations/anim_001.mp4",
  "duration_seconds": 8.0,
  "resolution": {"w": 1920, "h": 1080},
  "placement": {
    "type": "replace_segment | overlay | insert_after",
    "target_segment": "seg_005",
    "start_time": null
  },
  "voiceover_path": "audio/voiceover_anim_001.wav",
  "approved": false,
  "style_config_override": {}
}
```

## `thumbnails[]`

```json
{
  "id": "thumb_001",
  "path": "thumbnails/thumb_001.png",
  "source_frame": "frames/clip_001/frame_000150.jpg",
  "title_text": "Nepal's Tech Revolution",
  "subtitle_text": "",
  "style": "bold_text_overlay | minimal | dramatic",
  "resolution": {"w": 1280, "h": 720},
  "selected": false
}
```

## `outputs`

```json
{
  "long_16_9": {
    "blender_path": "blender/long_16_9.blend",
    "fcpxml_path": "exports/long_16x9.fcpxml",
    "resolution": {"w": 1920, "h": 1080},
    "fps": 30,
    "render_path": null,
    "render_status": "pending | rendering | complete | error"
  },
  "long_9_16": {
    "blender_path": "blender/long_9_16.blend",
    "fcpxml_path": "exports/long_9x16.fcpxml",
    "resolution": {"w": 1080, "h": 1920},
    "fps": 30,
    "render_path": null,
    "render_status": "pending"
  },
  "shorts": [
    {
      "id": "short_001",
      "title": "Why Nepal needs better internet infrastructure",
      "blender_path": "blender/short_001_9_16.blend",
      "fcpxml_path": "exports/short_001_9x16.fcpxml",
      "resolution": {"w": 1080, "h": 1920},
      "fps": 30,
      "render_path": null,
      "render_status": "pending",
      "segments": ["seg_003", "seg_005"],
      "duration_seconds": 55.0
    }
  ]
}
```

## `youtube`

```json
{
  "long_form": {
    "title": "Nepal's Tech Revolution — Why It Matters",
    "description": "In this video...\n\nTimestamps:\n0:00 Intro\n...",
    "tags": ["nepal", "tech", "politics"],
    "category_id": 28,
    "default_language": "ne",
    "default_audio_language": "ne",
    "privacy": "private",
    "chapters": [
      {"time": "0:00", "title": "Intro"},
      {"time": "2:30", "title": "The Problem"}
    ],
    "cards": [],
    "end_screen": {}
  },
  "shorts": [
    {
      "short_id": "short_001",
      "title": "#Nepal tech infrastructure 🇳🇵",
      "description": "...",
      "tags": [],
      "visibility": "private"
    }
  ]
}
```

## `units[]`

Units are **logical groupings within the global timeline** — one unit = one concept/topic. After decomposition, the main manifest tracks every unit and its directory. Each unit directory contains its own `footage_manifest.json` (same schema) scoped to that unit's clips.

**Units reference the global timeline** — they don't own copies of timeline data. A unit knows its `timeline_range` and `clip_ids` (which global timeline clips belong to it).

```json
{
  "units": [
    {
      "unit_id": "unit_001_video_intro",
      "unit_type": "video | screencast | audio | text_image | animation",
      "display_name": "Channel Intro",
      "dir": "units/unit_001_video_intro",
      "topic_cluster_id": "topic_001_intro",
      "clip_ids": ["tc_001"],
      "selected_source_clip_id": "clip_003",
      "deselected_source_clips": [
        {"clip_id": "clip_001", "reason": "Abruptly stopped at 0:42"},
        {"clip_id": "clip_002", "reason": "3 false starts in first 10s"}
      ],
      "timeline_range": {"start": 0.0, "end": 15.5},
      "total_duration_seconds": 15.5,
      "needs_animation": false,
      "status": "pending | in_progress | refined | approved",
      "approved": false
    }
  ]
}
```

**Unit types:**
- `video` — Camera footage (talking head, b-roll, outdoor, action)
- `screencast` — Screen recording content
- `audio` — Audio-only content; needs Remotion visual overlay
- `text_image` — Text / image content; needs Remotion conversion to video
- `animation` — Placeholder for Manim / Remotion animation inserts

**Unit naming:** `unit_{NNN}_{type}_{slug}` — slug derived from transcript content.

### `unit_info` (inside unit manifests only)

Each unit's own `footage_manifest.json` includes a `unit_info` block that
identifies it within the parent project:

```json
{
  "unit_info": {
    "unit_id": "unit_001_video_intro_talking",
    "unit_type": "video",
    "display_name": "Intro Talking Head",
    "parent_project": "/absolute/path/to/footage_project_20260313",
    "source_clip_id": "clip_001",
    "time_range": {"start": 0.0, "end": 45.0},
    "status": "pending",
    "approved": false,
    "notes": ""
  }
}
```

### Unit directory layout

Each unit directory mirrors the main project structure so scripts can run unchanged:

```
units/unit_001_video_intro_talking/
├── raw/                    # symlinks to relevant source clips
├── audio/denoised/         # symlinks to relevant audio
├── frames/clip_001/        # symlinks to relevant frames
├── analysis/…              # symlinks to relevant analysis JSONs
├── sfx/                    # per-unit SFX (generated during refinement)
├── music/                  # per-unit music
├── animations/             # per-unit animations
├── thumbnails/
├── blender/
├── tmp/
├── footage_manifest.json   # self-contained, same schema as main
└── style_config.json       # symlink to project style config
```

### Parallel agent workflow

After decomposition, each unit can be processed independently:

```bash
# Agent 1: refine unit 001 (SFX, animations, crops)
python3 scripts/generate_sfx.py units/unit_001_video_intro_talking/

# Agent 2: refine unit 002 (different unit, no conflicts)
python3 scripts/generate_sfx.py units/unit_002_screencast_demo/
```

Changes within a unit directory cannot affect other units. After all units
are refined, `merge_units.py` reassembles them into the main manifest.

## `pipeline_state`

```json
{
  "current_phase": 11,
  "completed_phases": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  "phase_results": {
    "1": {"status": "success", "timestamp": "2026-03-13T14:30:05Z"},
    "2": {"status": "success", "timestamp": "2026-03-13T14:30:15Z", "clips_found": 3},
    "3": {"status": "success", "timestamp": "2026-03-13T14:31:00Z"},
    "4": {"status": "success", "timestamp": "2026-03-13T14:35:00Z", "engine": "whisper"},
    "5": {"status": "success", "timestamp": "2026-03-13T14:33:00Z"},
    "6": {"status": "success", "timestamp": "2026-03-13T14:32:00Z"},
    "7": {"status": "success", "timestamp": "2026-03-13T14:36:00Z", "frames_extracted": 150},
    "8": {"status": "success", "timestamp": "2026-03-13T14:38:00Z"},
    "9": {"status": "skipped", "reason": "no_screen_recordings"},
    "10": {"status": "success", "timestamp": "2026-03-13T14:39:00Z"}
  },
  "errors": [],
  "warnings": ["deepfilternet not available, skipping noise removal"],
  "units_decomposed": true,
  "units_decomposed_at": "2026-03-13T14:40:00Z",
  "units_merged": false,
  "units_merged_at": null,
  "last_updated": "2026-03-13T14:39:00Z"
}
```

## `narrative` (Phase 11 Step 1 output)

```json
{
  "topic_clusters": [
    {
      "id": "topic_001_intro",
      "topic": "Channel introduction — who I am, what this channel is about",
      "clips": [
        {
          "clip_id": "clip_001",
          "selected": false,
          "reason": "Abruptly stopped at 0:42, incomplete thought"
        },
        {
          "clip_id": "clip_002",
          "selected": false,
          "reason": "3 false starts in first 10 seconds, low energy"
        },
        {
          "clip_id": "clip_003",
          "selected": true,
          "reason": "Cleanest delivery, no false starts, complete thought, highest energy"
        }
      ],
      "best_clip_id": "clip_003",
      "proposed_order": 1
    }
  ],
  "story_arc": ["topic_001_intro", "topic_002_problem", "topic_003_demo", "topic_004_conclusion"],
  "total_selected_clips": 4,
  "total_deselected_clips": 8
}
```

## `edit_manifest.json` — User Edits Layer

The edit manifest stores user edits from the studio session. It is a separate file (`edit_manifest.json`) alongside the footage manifest. The footage manifest has source data + global timeline; the edit manifest has user modifications.

```json
{
  "version": "1.0.0",
  "source_manifest_path": "footage_manifest.json",
  "created": "2026-03-14T10:00:00Z",
  "last_synced": "2026-03-14T11:30:00Z",
  "unit_order": ["unit_001_intro", "unit_002_hooks", "unit_003_demo"],
  "units": {
    "unit_001_intro": {
      "display_name": "Channel Intro",
      "unit_type": "video",
      "instructions": "Smooth transition at m1. Cut 5s of dead air around 0:32.",
      "bundle_clip_ids": ["clip_003"],
      "added_media": [],
      "markers": [
        {
          "id": "m1",
          "name": "transition point",
          "time": 15.3,
          "frame_number": 459,
          "position": {"x": 0.6, "y": 0.3},
          "type": "spatial",
          "source_clip_id": "clip_003"
        }
      ],
      "clip_edits": {
        "tc_001": {
          "trim": {"in": 5.0, "out": 23.5},
          "deleted_ranges": [
            {"start": 12.0, "end": 15.0, "reason": "dead air"}
          ],
          "splits": [
            {
              "at": 18.0,
              "produces": ["tc_001a", "tc_001b"]
            }
          ]
        }
      },
      "clip_moves": [],
      "word_cuts": [],
      "discarded_clips": ["clip_001", "clip_002", "clip_004", "clip_005"],
      "pipeline_requested": false,
      "needs_animation": false,
      "is_inserted": false,
      "status": "reviewing"
    }
  },
  "clip_moves": [
    {
      "clip_id": "tc_001b",
      "from_unit": "unit_001_intro",
      "to_unit": "unit_003_demo",
      "moved_at": "2026-03-14T11:25:00Z"
    }
  ],
  "claude_notes": {
    "unit_001_intro": {
      "notes": "Applied transition at m1. Removed 5s dead air at 0:32-0:37.",
      "updated": "2026-03-14T11:20:00Z"
    }
  },
  "session": {
    "started": "2026-03-14T10:00:00Z",
    "ended": null,
    "active": true
  }
}
```

**Key concepts:**
- `clip_edits` — per-timeline-clip modifications: trims, deleted ranges, splits. Applied to the global timeline before export.
- `clip_moves` — records of clips dragged between units. Global-level because they cross unit boundaries.
- `discarded_clips` — source clips deselected by narrative analysis or user. Visible in studio but not on timeline.
- `markers` — spatial (x,y + time) or temporal (time only) markers on clips. Referenced in instructions. See `studio-instruction-protocol.md`.
- `needs_animation` — per-unit flag. When true, the unit's footage is reference material and Phase 13 generates animation content for it.

## Script Interface Convention

Every pipeline script follows this interface:

```
python3 script.py <project_root> [--flags]
```

- Reads `{project_root}/footage_manifest.json`
- Writes results back to the same manifest
- Also writes detailed per-clip analysis to `{project_root}/analysis/...`
- Exits 0 on success, 1 on error
- Prints structured JSON to stdout on completion: `{"status": "success", "message": "...", "details": {...}}`
- Prints errors to stderr
- Is idempotent: running twice produces the same result (skips already-processed clips unless `--force`)
