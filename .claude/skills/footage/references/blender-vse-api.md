# Blender 4.5 Headless VSE Scripting Reference

## Invoking Blender Headlessly

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python script.py
```

- `--background`: no GUI, headless mode
- `--factory-startup`: ignore user preferences, start clean
- `--python script.py`: execute the given Python script then exit

Pass arguments to your script after `--`:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python script.py -- --input /abs/path/video.mp4 --output /abs/path/out.blend
```

Access script args via `sys.argv[sys.argv.index("--") + 1:]`.

## Core VSE Setup

```python
import bpy

# Start with a completely empty file (no default cube, camera, light)
bpy.ops.wm.read_homefile(use_empty=True)

scene = bpy.context.scene
scene.sequence_editor_create()
sed = scene.sequence_editor
```

`scene.sequence_editor_create()` initializes the Video Sequence Editor data block. Without this call, `scene.sequence_editor` is `None`.

## Adding Strips

### Video

```python
strip = sed.sequences.new_movie(
    name="footage",
    filepath="/absolute/path/to/video.mp4",
    channel=1,
    frame_start=1
)
```

### Audio

```python
audio = sed.sequences.new_sound(
    name="audio",
    filepath="/absolute/path/to/audio.wav",
    channel=2,
    frame_start=1
)
```

### Effects

```python
# Transform effect (applied to a source strip)
transform = sed.sequences.new_effect(
    name="transform_01",
    type='TRANSFORM',
    channel=5,
    frame_start=strip.frame_start,
    frame_end=strip.frame_final_end,
    seq1=strip
)

# Speed control
speed = sed.sequences.new_effect(
    name="speed_01",
    type='SPEED',
    channel=6,
    frame_start=strip.frame_start,
    frame_end=strip.frame_final_end,
    seq1=strip
)

# Cross dissolve (transition between two strips)
cross = sed.sequences.new_effect(
    name="cross_01",
    type='CROSS',
    channel=7,
    frame_start=100,
    frame_end=110,
    seq1=strip_a,
    seq2=strip_b
)

# Color strip (solid color, no source strip needed)
color = sed.sequences.new_effect(
    name="black",
    type='COLOR',
    channel=8,
    frame_start=1,
    frame_end=30
)
color.color = (0, 0, 0)  # RGB
```

## Strip Properties

| Property | Description |
|---|---|
| `strip.frame_start` | Frame where the strip begins on the timeline |
| `strip.frame_offset_start` | Frames trimmed from the source start |
| `strip.frame_final_duration` | Duration in frames after trimming |
| `strip.frame_final_end` | Computed: `frame_start + frame_final_duration` |
| `strip.channel` | Vertical channel (layer) in the VSE |

## Cropping

```python
strip.use_crop = True
strip.crop.min_x = 0      # pixels removed from left
strip.crop.max_x = 1312   # pixels removed from right
strip.crop.min_y = 0      # pixels removed from bottom
strip.crop.max_y = 0      # pixels removed from top
```

For a 1920x1080 source cropped to 608x1080 (9:16 portrait): `min_x + max_x = 1312`. Slide the crop window by adjusting `min_x` and `max_x` while keeping their sum constant at 1312.

## Keyframing

### Crop Keyframes

```python
# Set crop position at a specific frame
strip.crop.min_x = 200
strip.crop.max_x = 1112
strip.crop.keyframe_insert(data_path="min_x", frame=30)
strip.crop.keyframe_insert(data_path="max_x", frame=30)

# Move crop to new position at a later frame
strip.crop.min_x = 600
strip.crop.max_x = 712
strip.crop.keyframe_insert(data_path="min_x", frame=60)
strip.crop.keyframe_insert(data_path="max_x", frame=60)
```

### FCurve Easing

After inserting keyframes, modify interpolation on the FCurves:

```python
action = strip.crop.animation_data.action
for fcurve in action.fcurves:
    for kp in fcurve.keyframe_points:
        kp.interpolation = 'BEZIER'       # or 'SINE', 'EXPO', 'BACK', etc.
        kp.easing = 'EASE_IN_OUT'         # 'EASE_IN', 'EASE_OUT', 'EASE_IN_OUT'
```

Valid interpolation types: `CONSTANT`, `LINEAR`, `BEZIER`, `SINE`, `QUAD`, `CUBIC`, `QUART`, `QUINT`, `EXPO`, `CIRC`, `BACK`, `BOUNCE`, `ELASTIC`.

### Audio Volume Keyframes

```python
audio.volume = 1.0
audio.keyframe_insert(data_path="volume", frame=1)

audio.volume = 0.0
audio.keyframe_insert(data_path="volume", frame=30)
```

## Render Settings

```python
scene.render.resolution_x = 1080
scene.render.resolution_y = 1920
scene.render.fps = 30
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.audio_codec = 'AAC'
scene.render.ffmpeg.constant_rate_factor = 'HIGH'
scene.render.filepath = "/absolute/path/to/output.mp4"
scene.frame_start = 1
scene.frame_end = strip.frame_final_end
```

## Saving the Blend File

```python
bpy.ops.wm.save_as_mainfile(filepath="/absolute/path/to/project.blend")
```

## Channel Layout Convention

| Channel | Content |
|---|---|
| 1 | Primary video footage |
| 2 | Primary audio (dialogue) |
| 3 | Sound effects |
| 4 | Background music |
| 5+ | Effects (transforms, crops, transitions) |

Higher channels render on top of lower channels when strips overlap.

## Blender 4.5 Gotchas

- **Frame numbering starts at 1**, not 0. Setting `frame_start=0` can cause off-by-one errors and unexpected behavior with effects.
- **All file paths must be absolute.** Blender in headless mode does not resolve relative paths reliably. Always use `os.path.abspath()`.
- **`new_movie()` does not import audio.** You must add a separate `new_sound()` strip for the audio track from the same file.
- **`frame_final_duration` is read-only in some contexts.** Set `frame_offset_start` and `frame_offset_end` to control trim points instead.
- **Factory startup resets everything.** `--factory-startup` means no addons are loaded. If you need an addon, enable it in your script via `bpy.ops.preferences.addon_enable(module="addon_name")`.
