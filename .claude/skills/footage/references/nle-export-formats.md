# NLE Export Formats

The pipeline supports multiple NLE (Non-Linear Editor) export targets. Each is a standalone script that reads the manifest and produces project files.

## Supported Formats

### Blender VSE (`build_blender_project.py`)
- **Output**: `.blend` files in `blender/`
- **Requires**: Blender 4.x installed (runs headlessly)
- **Features**: Full support for video segments, SFX, music with ducking keyframes, animation inserts, 9:16 crop with easing keyframes, speed changes, transitions
- **Formats**: 16:9 long, 9:16 long, 9:16 shorts

### FCPXML 1.9 (`export_fcpxml.py`)
- **Output**: `.fcpxml` files in `exports/`
- **Requires**: Nothing (pure XML generation)
- **Importable by**: DaVinci Resolve, Final Cut Pro, Adobe Premiere
- **Features**: Video segments with in/out points, transitions (Cross Dissolve, Dip to Color), SFX as connected clips, music with volume keyframes, speed changes via timeMap, animation inserts as asset clips
- **Formats**: 16:9 long, 9:16 long, 9:16 shorts
- **Limitation**: Animated crop keyframes cannot be expressed natively in FCPXML across NLEs. For 9:16 format, crop data is encoded as timeline markers — apply manually in the NLE.

## FCPXML Version Compatibility

**FCPXML 1.9 is targeted intentionally.** DaVinci Resolve does NOT reliably import FCPXML 1.10 or 1.11. Final Cut Pro supports all versions. Premiere supports 1.9+. Targeting 1.9 maximizes compatibility across all three NLEs.

## DaVinci Resolve Import Instructions

1. Open DaVinci Resolve
2. Go to **File → Import Timeline → Import AAF/EDL/XML...**
3. Select the `.fcpxml` file from `exports/`
4. In the import dialog:
   - Ensure **"Automatically import source clips into media pool"** is checked
   - Set frame rate to match the project (default 30fps)
5. The timeline will appear in the current bin with all clips, transitions, and audio

### 9:16 Crop Markers (DaVinci Resolve)

For vertical (9:16) exports, crop keyframes are encoded as timeline markers since FCPXML cannot express animated crops portably. In DaVinci Resolve:
1. Set project resolution to 1080×1920
2. Open the **Marker** panel
3. Each marker contains crop coordinates (`x,y,w,h`) and easing type
4. Apply crops manually using the **Inspector → Transform** panel
5. Use Resolve's keyframe editor to animate between crop positions

### Final Cut Pro Import

Final Cut Pro imports FCPXML natively:
1. **File → Import → XML...**
2. Select the `.fcpxml` file
3. All assets, clips, and timeline structure will import directly

### Adobe Premiere Import

1. **File → Import**
2. Select the `.fcpxml` file
3. Premiere will create a sequence matching the timeline structure

## Future Formats

Potential additions (not yet implemented):
- **OpenTimelineIO (OTIO)** — ASWF standard, growing NLE support
- **EDL (Edit Decision List)** — Legacy format, limited feature support
- **AAF (Advanced Authoring Format)** — Binary format, Avid-centric

## Output Directory Structure

```
exports/
├── long_16x9.fcpxml      # 16:9 long-form timeline
├── long_9x16.fcpxml      # 9:16 long-form (vertical) timeline
├── short_001_9x16.fcpxml # Per-short vertical timelines
├── short_002_9x16.fcpxml
└── ...
```

Manifest tracks export paths in `outputs.long_16_9.fcpxml_path`, `outputs.long_9_16.fcpxml_path`, and `outputs.shorts[].fcpxml_path`.
