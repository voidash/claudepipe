# Remotion Full-Video Compositing

Reference for using Remotion as a full compositing engine — not just isolated clips, but the entire source footage with overlays, VFX, rotoscoping, and transitions rendered as a single output.

## When this applies

Phase 13 animations can range from simple motion graphics (title cards, diagrams) to full-video compositing where Remotion layers effects over the entire source footage. This doc covers the full compositing case.

## The FullVideo Pattern

One root composition that layers everything:

```tsx
import { AbsoluteFill, OffthreadVideo, Sequence, staticFile } from "remotion";

const SOURCE_DURATION_S = 98.752;
const FPS = 30;
const SOURCE_FRAMES = Math.ceil(SOURCE_DURATION_S * FPS);

// Marker times from edit_manifest → frame positions
const M1_FRAME = 0;
const M2_FRAME = Math.round(34.367 * FPS);

const OVERLAY_1_FRAMES = 120;  // 4s
const TRANSITION_FRAMES = 90;  // 3s end card

export const FULL_VIDEO_DURATION = SOURCE_FRAMES + TRANSITION_FRAMES;

export const FullVideo: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: "#000" }}>
    {/* Bottom: Source footage */}
    <Sequence durationInFrames={SOURCE_FRAMES}>
      <AbsoluteFill>
        <OffthreadVideo
          src={staticFile("source.MP4")}
          style={{ width: 1920, height: 1080, objectFit: "cover" }}
        />
      </AbsoluteFill>
    </Sequence>

    {/* Middle: Overlays at marker times */}
    <Sequence from={M1_FRAME} durationInFrames={OVERLAY_1_FRAMES}>
      <AbsoluteFill><LogoReveal /></AbsoluteFill>
    </Sequence>

    {/* Top: VFX spanning entire source */}
    <Sequence durationInFrames={SOURCE_FRAMES}>
      <AbsoluteFill><VFXOverlay /></AbsoluteFill>
    </Sequence>

    {/* After source: End card */}
    <Sequence from={SOURCE_FRAMES} durationInFrames={TRANSITION_FRAMES}>
      <AbsoluteFill><EndCard /></AbsoluteFill>
    </Sequence>
  </AbsoluteFill>
);
```

**Key:** Later `<AbsoluteFill>` children render on top. Source at bottom, graphics in middle, VFX on top.

## Rotoscoping — Person Segmentation Layer

Use ML segmentation to make graphics appear *behind* a person.

### Layer sandwich

```
z-index 3 (top):     Rotoscoped person (OffthreadVideo transparent, WebM VP9 alpha)
z-index 2 (middle):  Graphics/logos overlay (transparent background)
z-index 1 (bottom):  Source footage (OffthreadVideo)
```

### Generate person cutout

Python script using rembg (not the CLI — broken on Python 3.14+):

```python
from rembg import remove, new_session
from PIL import Image
import subprocess, os

FPS = 30
DURATION_S = 4.0
FRAME_COUNT = int(FPS * DURATION_S)

def extract_frames(tmpdir, source_video):
    subprocess.run([
        "ffmpeg", "-y", "-i", str(source_video),
        "-ss", "0", "-t", str(DURATION_S),
        "-vf", f"scale=1920:1080,fps={FPS}",
        "-start_number", "0",
        os.path.join(tmpdir, "source_%04d.png"),
    ], check=True)

def segment_persons(tmpdir):
    session = new_session("u2net_human_seg")  # fast, good for people
    for i in range(FRAME_COUNT):
        img = Image.open(os.path.join(tmpdir, f"source_{i:04d}.png"))
        result = remove(img, session=session)
        result.save(os.path.join(tmpdir, f"person_{i:04d}.png"))

def encode_webm(tmpdir, output_path):
    subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", os.path.join(tmpdir, "person_%04d.png"),
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-crf", "20", "-b:v", "0", "-an",
        str(output_path),
    ], check=True)
```

Performance: ~0.5s/frame with `u2net_human_seg`. 120 frames (4s) ≈ 60s. Output: ~3MB WebM for 4s 1920x1080.

### rembg model options

| Model | Speed | Quality | Use case |
|-------|-------|---------|----------|
| `u2net_human_seg` | Fast (~0.5s/f) | Good | People, indoor |
| `u2net` | Medium | Better edges | General objects |
| `birefnet-portrait` | Slow (~2s/f) | Best edges | Hair/clothing detail |

Always use the Python API (`from rembg import remove`), not the CLI entry point.

### Use in Remotion

```tsx
<Sequence from={0} durationInFrames={120}>
  {/* Graphics layer (behind person) */}
  <AbsoluteFill><LogoReveal /></AbsoluteFill>

  {/* Person foreground (alpha-masked) */}
  <AbsoluteFill>
    <OffthreadVideo
      src={staticFile("person_rotoscope.webm")}
      transparent
      style={{ width: 1920, height: 1080, objectFit: "cover" }}
    />
  </AbsoluteFill>
</Sequence>
```

The `transparent` prop tells Remotion to respect the WebM alpha channel.

### Positioning graphics relative to the person

The person's silhouette occludes everything behind it. Graphics directly behind the body are invisible. You MUST:

1. **Analyze the rotoscope mask first** — extract a frame to see where the person IS:
```bash
ffmpeg -i person_rotoscope.webm -vf "select=eq(n\,50)" -frames:v 1 -update 1 mask_check.png
```

2. **Position at frame edges** where background is visible (not behind the person's torso)

3. **Verify with still renders** before presenting to user:
```bash
npx remotion still src/index.ts FullVideo out/check.png --frame=50
```

## VFX Overlay System

A single component that renders different visual effects based on frame number. Content-aware: analyze footage first, map segments, assign effects.

### Workflow

1. Extract thumbnails to understand content:
```bash
ffmpeg -i source.mp4 -vf "fps=1/5,scale=960:540" thumbs/thumb_%03d.jpg
```

2. Map content segments (time → frame at 30fps):
```
0-150:     Intro talking
150-300:   Notes closeup
300-1030:  Talking head (animated)
1050-1950: Screen recording (Blender)
1950-2700: Rendered animation
```

3. Assign effects per segment, build one component.

### Architecture

```tsx
export const VFXOverlay: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <div style={{
      position: "absolute", width: WIDTH, height: HEIGHT,
      overflow: "hidden", pointerEvents: "none",
    }}>
      <Vignette />
      <RedCircleMeme frame={frame} />
      <SpeedLines frame={frame} />
      <FloatingEmojis frame={frame} fps={fps} />
      <EmphasisFlash frame={frame} />
      <PopText frame={frame} fps={fps} />
      <TechHUD frame={frame} fps={fps} />
      <CinematicOverlay frame={frame} fps={fps} />
    </div>
  );
};
```

### Effect catalog

| Effect | Use case | Technique |
|--------|----------|-----------|
| **Speed Lines** | Emphasis moments, talking head energy | SVG radiating lines from center, burst timing arrays |
| **Floating Emoji** | Reactions, fun moments | Spring-animated emoji rising from bottom with wobble |
| **Pop Text** | Impact moments ("POW", "WOW") | Scale 4→1 spring slam, WebkitTextStroke for comic effect |
| **Red Circle Meme** | Drawing attention to something | SVG ellipse with dashoffset animation, arrow appears after |
| **Tech HUD** | Screen recordings, tech demos | Corner brackets, scanline, monospace label, frame counter |
| **Cinematic Overlay** | Polished sections, renders | Letterbox bars, film grain (feTurbulence), stamp |
| **Vignette** | Always on | radial-gradient transparent→rgba(0,0,0,0.4) |
| **Emphasis Flash** | Quick impact | White flash, opacity 0.4→0 over 8 frames |

### Tips

- **Always `pointerEvents: "none"`** on VFX elements
- **SVG for geometric effects** — scales cleanly
- **CSS filter for color effects** — `sepia() hue-rotate() saturate() brightness()` chain
- **Film grain via feTurbulence** — change `seed` per frame for animated noise
- **Verify with still renders** before showing anyone

## Logo Animation

Real brand logos expanding from center with color transitions.

### Logo assets

Use real logos, not hand-drawn SVG approximations:
- Download SVGs from Wikimedia Commons, Bootstrap Icons, UXWing
- Download PNGs from brand pages (freelogovectors.net, icons8)
- Place in `public/logos/`

**Critical**: If an SVG uses `fill="currentColor"`, change it to the actual brand color. When loaded via `<Img>`, `currentColor` resolves to black.

### Center-outward expansion

All logos start at frame center and spring to target coordinates:

```tsx
const ORIGIN_X = WIDTH / 2;
const ORIGIN_Y = HEIGHT / 2;

const LOGOS = [
  { label: "Claude", src: "logos/claude.svg", targetX: 1680, targetY: 250, size: 200 },
  { label: "Blender", src: "logos/blender.svg", targetX: 200, targetY: 750, size: 220 },
  { label: "FCP", src: "logos/fcp.png", targetX: 1680, targetY: 750, size: 200 },
];

// Per logo:
const posDriver = spring({ frame, fps, delay, config: { damping: 12, stiffness: 100, mass: 0.9 } });
const x = interpolate(posDriver, [0, 1], [ORIGIN_X, logo.targetX]) - logo.size / 2;
const y = interpolate(posDriver, [0, 1], [ORIGIN_Y, logo.targetY]) - logo.size / 2;
const scale = interpolate(posDriver, [0, 1], [0.3, 1]);
```

### Green → brand color transition

CSS filter tints all logos uniformly, then interpolates to real colors:

```tsx
const colorDriver = spring({ frame, fps, delay: colorDelay, config: { damping: 20, stiffness: 60, mass: 1.2 } });

const sepia = interpolate(colorDriver, [0, 1], [1, 0]);
const hueRotate = interpolate(colorDriver, [0, 1], [80, 0]);
const saturate = interpolate(colorDriver, [0, 1], [5, 1]);
const brightness = interpolate(colorDriver, [0, 1], [0.65, 1]);

const filter = sepia > 0.01
  ? `sepia(${sepia}) hue-rotate(${hueRotate}deg) saturate(${saturate}) brightness(${brightness})`
  : "none";

// Opacity: 0.5 when green → 1.0 at full brand color
const colorOpacity = interpolate(colorDriver, [0, 1], [0.5, 1]);
```

This works on SVGs, PNGs, and any image format — the filter operates on rendered pixels.

### Motion typography

Word-by-word text reveal using staggered springs:

```tsx
const WORDS = ["video", "banaune", "josh", "aako", "cha"];
const WORD_STAGGER = 7; // frames between each word

{WORDS.map((word, i) => {
  const driver = spring({ frame, fps, delay: i * WORD_STAGGER, config: { damping: 12, stiffness: 130, mass: 0.7 } });
  const translateY = interpolate(driver, [0, 1], [50, 0]);
  const scale = interpolate(driver, [0, 1], [0.2, 1]);
  const rotation = interpolate(driver, [0, 1], [8, 0]);

  return (
    <span key={i} style={{
      display: "inline-block", // REQUIRED for transform to work on inline elements
      opacity: driver,
      transform: `translateY(${translateY}px) scale(${scale}) rotate(${rotation}deg)`,
    }}>
      {word}
    </span>
  );
})}
```

Emphasize key words with larger size, different color, glow `textShadow`.

## Using Remotion's `<Img>` component

Always use `<Img>` from `remotion`, not raw `<img>`:
- `<Img>` calls `delayRender()` automatically
- Blocks frame capture until image loads
- Handles retries on load failure

```tsx
import { Img, staticFile } from "remotion";

<Img
  src={staticFile("logos/blender.svg")}
  style={{ width: 200, height: 200, objectFit: "contain" }}
/>
```

## Source files in public/

`staticFile()` references files in `public/`. Remotion copies `public/` to a temp bundle dir during render — **symlinks break**. Copy actual files into `public/`.

## Render commands

```bash
# Full composited video
npx remotion render src/index.ts FullVideo out/full.mp4 --codec=h264 --crf=18

# Single frame check (ALWAYS do this before showing to user)
npx remotion still src/index.ts FullVideo out/check.png --frame=400

# Preview in Studio
npx remotion studio src/index.ts
```

## What this replaces

Full Remotion compositing replaces:
- Manual NLE compositing (DaVinci, FCP, Premiere) for overlay-heavy content
- FFmpeg filter_complex chains for overlay timing
- FCPXML/AAF project file generation for simple overlay cases

The tradeoff: no real-time scrubbing (Remotion renders each frame), but you get deterministic, version-controlled, code-driven compositing.

## Connection to pipeline phases

- **Phase 13** generates the Remotion code and renders it
- **Edit manifest markers** (m1, m2, ...) map to `Sequence from={}` frame positions
- **Source clip** in `raw/` gets copied to `public/` for `staticFile()` access
- **Rotoscope assets** (WebM alpha) go in `public/` alongside the source
- **Output** goes to `animations/{unit_id}_overlays/out/` and gets registered in edit_manifest as `added_media`
