# Source Screenshot Pipeline

Technical reference for capturing news/report sources as visual citations with automatic highlight coordinate extraction.

## Overview

When the script references a factual claim with a citation, the pipeline captures the source webpage as a high-resolution screenshot, extracts the bounding box of the key text, and saves coordinates for the Remotion highlighter overlay.

## Pipeline Steps

### 1. Source URL Collection (Phase 11b)

During research, every citable claim gets a source URL saved in `assets/source_urls.json`:

```json
{
  "source_13182_rounds": {
    "url": "https://kathmandupost.com/national/...",
    "title": "2,642 rounds of live ammunition fired...",
    "domain": "kathmandupost.com",
    "date": "2025-09-12",
    "claim": "13,182 rounds fired over 2 days"
  }
}
```

### 2. Screenshot Capture (Phase 11c)

**Playwright** captures each URL at 2x Retina resolution for crisp text:

```python
context = browser.new_context(
    viewport={"width": 1440, "height": 900},
    device_scale_factor=2,  # 2x = 2880x1800 actual pixels
    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
)
```

**Cookie/overlay dismissal** runs before capture:
- Clicks common accept/agree buttons (tries 18+ selectors)
- Removes fixed/sticky elements taller than 100px via JS
- Re-enables scrolling if the cookie banner locked `body.overflow`

### 3. Highlight Coordinate Extraction

After the page loads and cookies are dismissed:

```python
# Search for the claim text on the page
search_text = " ".join(claim.split()[:6])  # First 6 words
loc = page.get_by_text(search_text, exact=False).first

# Scroll to it and get pixel coordinates
loc.scroll_into_view_if_needed()
box = loc.bounding_box()

# Scale by device_scale_factor for actual pixel coords in the PNG
highlight_box = {
    "x": round(box["x"] * 2),      # 2 = device_scale_factor
    "y": round(box["y"] * 2),
    "width": round(box["width"] * 2),
    "height": round(box["height"] * 2)
}
```

**Important:** `bounding_box()` returns CSS pixels. The PNG is captured at `device_scale_factor=2`, so coordinates must be multiplied by the scale factor to match actual pixel positions in the image.

Coordinates are saved to `assets/sources/highlight_coordinates.json`:

```json
{
  "source_13182_rounds": {
    "url": "https://kathmandupost.com/...",
    "claim": "13,182 rounds fired over 2 days",
    "highlight_box": {"x": 242, "y": 610, "width": 1564, "height": 160}
  }
}
```

If `get_by_text()` can't find the claim (different wording, JS-rendered content), `highlight_box` is `null` — the Remotion component falls back to a full-width highlight at the article headline.

### 4. Grungy Highlighter Overlay (Remotion or PIL)

The highlight is NOT a clean rectangle. It's designed to look like a real marker on paper.

**PIL implementation (for static preview/testing):**

```python
from PIL import Image, ImageDraw, ImageFilter
import random

# Load screenshot and coordinates
img = Image.open("source.png")
box = highlight_box  # from JSON

highlight = Image.new("RGBA", img.size, (0, 0, 0, 0))
draw = ImageDraw.Draw(highlight)

x, y, w, h = box["x"], box["y"], box["width"], box["height"]

# Add padding for marker bleed
pad = 12
x -= pad
y -= pad // 2
w += pad * 2
h += pad

# Draw 8 overlapping passes with random offsets for hand-drawn feel
random.seed(42)
for i in range(8):
    ox = random.randint(-6, 6)      # Horizontal wobble
    oy = random.randint(-4, 4)      # Vertical wobble
    ow = random.randint(-10, 10)    # Width variation
    oh = random.randint(-3, 3)      # Height variation
    alpha = random.randint(120, 180) # Opacity variation (not uniform)
    color = (255, 224, 50, alpha)    # Yellow highlighter

    draw.rounded_rectangle(
        [x + ox, y + oy, x + w + ow, y + h + oh],
        radius=4,
        fill=color
    )

# Blur for marker bleed effect
highlight = highlight.filter(ImageFilter.GaussianBlur(3))

# Composite over screenshot
result = Image.alpha_composite(img.convert("RGBA"), highlight)
```

**Why 8 passes:** A single rectangle looks digital. 8 overlapping rectangles with random offsets, varying opacity, and slight size differences create the effect of a real marker stroke where ink accumulates unevenly — thicker in the middle, thinner at edges, slightly wobbly path.

**Remotion implementation:** The same logic as an SVG/canvas overlay component that reads `highlight_coordinates.json` and draws the marker effect. The highlight animates in (draws left-to-right over 0.3-0.5s) after the screenshot slides on screen.

### 5. Color Variants

| Color | RGBA | Use case |
|-------|------|----------|
| Yellow | (255, 224, 50, α) | Standard citation highlight |
| Red | (255, 68, 68, α) | Critical/alarming claims |
| Green | (68, 200, 68, α) | Positive/reform claims |

Alpha varies per pass: 120-180 (not uniform).

### 6. Quality Checklist

- [ ] Screenshot is at `device_scale_factor=2` (2880x1800 minimum for 1440 viewport)
- [ ] Cookie/overlay banners dismissed before capture
- [ ] URL bar and site branding visible in the capture
- [ ] `highlight_box` is not `null` (text was found on the page)
- [ ] Highlight coordinates are scaled by `device_scale_factor`
- [ ] Highlighted text matches the claim (not a random element)

### 7. Fallback Chain

If `get_by_text()` fails to find the claim:
1. Try fewer words (first 3 instead of 6)
2. Try the article headline text
3. Try `page.locator('h1')` or `page.locator('article h1')` for the headline
4. If all fail, set `highlight_box: null` — Remotion uses a default full-width highlight on the top headline

### 8. File Structure

```
assets/sources/
  source_urls.json                  # URL + claim for each source
  highlight_coordinates.json         # Bounding boxes for all sources
  source_13182_rounds.png           # Screenshot (2x viewport)
  source_hrw_14yo.png               # Screenshot (2x viewport)
  ...
```

### 9. Known Issues

- **Paywalled articles**: Playwright can't get past hard paywalls. For paywalled sources, use the Google Cache or Wayback Machine URL instead.
- **JS-heavy sites**: Some sites render content via JavaScript after page load. The `wait_for_timeout(2500)` handles most, but SPA-heavy sites may need `wait_for_selector` on the article body.
- **Cookie banners that persist**: Some sites use shadow DOM or iframes for cookie banners that the JS removal can't reach. These show up in screenshots. Manual cleanup in image editor is the fallback.
- **Right-to-left text**: `bounding_box()` works correctly for RTL text but the highlight draw direction should reverse for the animation.
