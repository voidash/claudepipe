# Screen Recording Synchronization

Reference for detecting screen recordings and synchronizing them with camera footage.

## Detection

Screen recordings are identified via heuristic scoring. Each heuristic contributes a weighted score; a combined threshold determines classification.

| Heuristic | Signal |
|-----------|--------|
| Resolution | Exact monitor resolutions (2560x1440, 1920x1080, etc.) score higher |
| Frame rate | Fixed 30 or 60 fps without variation (no dropped frames) |
| Codec / container | Common screen-capture codecs (h264 from OBS, ProRes from QuickTime) |
| Metadata | Presence of screen-capture software tags (OBS, QuickTime, ScreenFlow) |
| Filename | Patterns like `screen-*`, `recording-*`, `Screen Recording*` |

If the total heuristic score exceeds the detection threshold, the file is flagged as a screen recording in the manifest.

## Audio Sync via Cross-Correlation

Screen recordings that include system audio or mic audio are synchronized to the camera footage using audio cross-correlation.

### Method

Use `scipy.signal.fftconvolve` on the audio waveforms to find the time offset that maximizes correlation.

### Performance strategy

1. **Initial search**: Downsample both audio tracks to 8 kHz. Analyze only the first 60 seconds. This produces a coarse offset estimate quickly.
2. **Refinement**: Resample to 16 kHz around the coarse offset (a 5-second window). Re-run correlation for sub-frame precision.

### Minimum correlation score

A correlation score below **0.3** means no reliable match was found. In that case, do not auto-sync. Log a warning and prompt the user for manual alignment or to confirm there is no shared audio.

## Compositing Layout Options

After sync, the screen recording and camera footage must be composited. Present these layout options to the user for approval.

### PiP (Picture-in-Picture)

Camera footage fills the frame; screen recording appears as a small overlay (typically bottom-right, 25-30% of frame width). Best for **16:9** output where screen content is supplementary.

### Split

Top/bottom split — camera on top, screen on bottom (or vice versa). Best for **9:16** (vertical/short-form) output where both sources need equal visibility.

### Switch

Alternate between full-frame camera and full-frame screen recording based on context. Cut to screen when new content appears; cut back to camera during explanation. Best when the screen content changes infrequently and you want maximum resolution for both.

### Side-by-Side

Left/right split, each source taking half the frame. Only suitable for **16:9** output. Useful when both sources need simultaneous visibility and PiP would make the screen recording too small to read.

## Approval

The user always approves the layout choice. Never auto-select a layout. Present the options with a recommendation based on the output format (16:9 vs 9:16) and the nature of the screen content, but wait for confirmation before proceeding.
