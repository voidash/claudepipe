# Source Citation Visual Style

When referencing news sources, research papers, or web content in the video, present them as **real browser screenshots with grungy highlighter markup** — not clean text cards.

## The Look

Think: someone printed the article, grabbed a yellow highlighter, and aggressively marked the key passage. Then scanned it. The paper has texture, the highlight bleeds at the edges, and there's maybe a coffee ring or a fold mark.

## Composition Layers (bottom to top)

1. **Paper texture background** — slightly off-white, visible fiber/grain, subtle wrinkles
2. **Browser screenshot** — the actual webpage showing:
   - URL bar with the full URL visible
   - Site navbar/header with the portal's branding (logo, name)
   - The article content with headline visible
   - The key passage in context (not isolated — surrounding text visible too)
3. **Highlighter overlay** — grungy, imperfect yellow highlight over the key text:
   - NOT a perfect rectangle — edges are rough, bleeds slightly outside the lines
   - Opacity varies (70-90%) like a real highlighter on paper
   - Slight rotation (1-3 degrees) like someone drew it by hand
   - Can overlap multiple lines — doesn't snap to text boundaries perfectly
   - Color: yellow (#FFE033) at 75% opacity for standard, red (#FF4444) at 60% for critical
4. **Film grain overlay** — subtle, matching the project's overall grain level
5. **QR code** — bottom corner, small (120x120px), links to the source URL. Clean white background with rounded corners so it's scannable.
6. **Source label** — small text below the screenshot: domain name + date. Sans-serif, muted color.

## Animation

**Entry:** The "page" slides up from below (spring animation, 0.5s), as if being placed on a desk.
**Highlight:** The highlighter mark draws on 0.3-0.5s AFTER the page arrives — like someone is actively marking it. Draw from left to right with slight wobble.
**Exit:** Page slides down or fades after 3-5s of being visible.
**SFX:** Subtle paper shuffle sound on entry. Optional marker squeak on highlight (very subtle, don't overdo it).

## How to Capture the Screenshot

During the research phase (Phase 11b), when YouTube transcripts reference a source or when the user provides article URLs:

1. Use Playwright/Puppeteer to screenshot the actual webpage
2. Capture at 1280x900 viewport (standard browser)
3. Include the URL bar and site navigation in the capture
4. Crop to show the relevant section + surrounding context
5. Save as PNG in `assets/sources/`

If the source is from a YouTube transcript (no direct URL), capture a Google search result showing the claim, or use the YouTube video itself as the source (screenshot of the video at the relevant timestamp with the channel name visible).

## Implementation in Remotion

```tsx
// Conceptual — not final code
<SourceCitation
  screenshotPath="assets/sources/kathmandu_post_article.png"
  highlightRegion={{x: 120, y: 340, width: 680, height: 45}}
  highlightColor="yellow"  // or "red" for critical
  sourceUrl="https://kathmandupost.com/..."
  sourceDomain="Kathmandu Post"
  sourceDate="2026-01-30"
  qrCode={true}
  entryAnimation="slide_up"
  duration={4}  // seconds
/>
```

## The Highlighter Effect (CSS/Canvas)

The highlight must NOT look digital. Achieve this with:
- SVG path with `stroke-dasharray` and hand-drawn wobble via perlin noise on the path
- OR: pre-rendered highlight textures (5-6 variations) applied as masks
- Opacity variation along the stroke (thicker in the middle, fading at edges)
- Slight color bleed beyond the text bounds (2-4px)
- Random rotation per highlight instance (1-3 degrees)

## When to Use

- Every factual claim that has a citable source
- Direct quotes from articles
- Statistics or data points
- Historical facts that viewers might question
- Legal/policy references

## When NOT to Use

- Common knowledge ("Nepal is in Asia")
- The creator's own opinions
- Rhetorical questions
- Song lyrics being discussed (the song itself is the source — show the video, not an article)

## Johnny Harris Connection

In the JH style profile, this maps to "key concept pop-out" but with source credibility added. JH uses bold white text on black boxes — we extend that with the actual source context visible. The grungy highlighter adds the investigative/documentary feel that matches the overall aesthetic.
