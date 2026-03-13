# claudepipe

AI video editing pipeline as a [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skill. Raw camera footage + screen recordings → fully edited NLE projects.

Claude analyzes your footage, makes editing decisions (cuts, transitions, crop keyframes), and produces Blender VSE and/or FCPXML projects importable by DaVinci Resolve, Final Cut Pro, and Premiere.

Built for a Nepali+English code-switching workflow but works with any language Gemini ASR supports.

## Install

```bash
git clone git@github.com:voidash/claudepipe.git
cd claudepipe
claude  # start Claude Code
```

Claude Code discovers the skill from `.claude/skills/footage/SKILL.md`.

## Usage

```
/footage
```

Claude asks for source files, a topic hint, and any special instructions, then runs a 20-phase pipeline:

| Phase | What happens |
|-------|-------------|
| 1–2 | Setup, scan files with ffprobe, classify camera vs screencast |
| 3–4 | Extract audio, transcribe (Gemini ASR, Nepali+English) |
| 5–6 | VAD + pitch analysis, scene boundary detection |
| 7–9 | Frame extraction, YOLO detection, Claude vision analysis |
| 10 | Screen recording sync (cross-correlation) |
| 11 | Build editorial timeline with interest scores + crop keyframes |
| 11b | Decompose into isolated units (parallel agent processing) |
| 12 | **Review** — you approve/edit each unit's cuts and transitions |
| 13–15 | Animations, SFX (ElevenLabs), background music (Gemini) |
| 16 | Thumbnails |
| 17 | **Build NLE projects** — Blender and/or FCPXML |
| 18–20 | Validation, YouTube metadata, cleanup |

Phases in **bold** are conversational — Claude presents options and waits for your input.

## Architecture

**Manifest-driven**: `footage_manifest.json` is the single source of truth. Every phase reads/writes it. See [`manifest-schema.md`](.claude/skills/footage/references/manifest-schema.md) for the full schema.

**Unit isolation**: After analysis, the timeline is decomposed into independent units (video, screencast, audio, text+image, animation). Each unit gets its own directory and manifest. Parallel Claude Code agents can refine different units simultaneously without conflicts.

**Scripts are optional**: Reference implementations live in `scripts/`. Claude uses them for complex phases (Blender assembly, FCPXML export, YOLO, VAD, scene detection) and works inline for simpler ones. `SKILL.md` describes *what* each phase does — that's the spec, not the scripts.

**Multi-NLE output**:
- **Blender VSE** — headless .blend generation with full timeline, SFX, music ducking, animated 9:16 crops
- **FCPXML 1.9** — imports into DaVinci Resolve, Final Cut Pro, Premiere

## Dependencies

### Critical
- ffmpeg / ffprobe
- Blender ≥ 4.x
- Python 3.10+
- ultralytics (YOLO), opencv-python, numpy

### Required
- librosa, scipy, pydub, torch, Pillow

### Optional
- google-genai (Gemini ASR + music generation)
- elevenlabs (SFX generation)
- manim (math/diagram animations)
- Node.js/npx (Remotion animations)
- deepfilternet (audio denoising)

## File Structure

```
.claude/skills/footage/
├── SKILL.md              # Pipeline spec (the brain)
├── scripts/              # 19 reference implementation scripts
├── references/           # 10 technical reference docs
└── templates/            # Style config defaults
```

## License

MIT
