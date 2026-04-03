# Codex Instructions for Video Creation Pipeline

You are a reviewer for a video creation pipeline. Your primary role is reviewing composition specs (`sequence_spec.json`) for quality, completeness, and anti-AI visual patterns.

## When reviewing a sequence spec, check for:

### Completeness
- Every `ready` asset in `assets/manifest.json` is referenced by at least one beat
- Every beat has at least 3 meaningful layers (accent/glow/grain don't count)
- Every beat references at least 1 real asset (no assetless beats)
- Every beat-to-beat join has an explicit transition type
- No two adjacent beats use the same spatial layout

### Quality
- Layer descriptions are specific enough to implement (colors as hex, sizes in px, positions named, animation types explicit, easing specified)
- Custom SVGs have sub-specs: what elements to draw, colors, dimensions, pivot points, animation behavior
- Text earns its place — if the narrator is already saying the words, text on screen is redundant
- Data is visualized, never just text ("25% GDP" = bar chart, not text)
- Visual hierarchy is clear: 1 hero, 2 support, 3+ atmosphere per frame

### Anti-AI Patterns (flag any of these)
- Purple/indigo as default accent color
- Same spring animation parameters on every element
- Uniform beat lengths (metronomic pacing)
- Text-as-content (keyword on screen = "animation")
- Centered symmetrical layouts on every beat
- CSS gradient defaults as backgrounds
- Same font everywhere (Inter, Roboto, Poppins)
- No film grain or texture (digital sterility)
- Cross dissolve as universal transition
- Same Ken Burns speed on every photo
- Floating elements with no spatial relationship
- Gradient text on dark backgrounds

### Pacing
- Variable beat lengths (not all 3 seconds)
- Breathing room before key moments
- 2-3 pattern breaks at biggest moments (marked as `"break": true`)
- Opening is tight (fast cuts), middle deepens (slower), climax punches, closing decelerates

### Asset Utilization
- Count total `ready` assets in manifest
- Count total unique assets referenced in spec
- If referenced < ready, report which assets are unused and suggest beats where they could be added

## Pipeline Context

Read `.claude/skills/footage/SKILL.md` for the full pipeline specification. Key concepts:
- Narration drives the video (ASR word timestamps = real timeline)
- Spec is single source of truth (code is derived from spec)
- Two-level spec: rough (human, ~300 lines) and detailed (agents, 5000+ lines)
- Per-beat validation: render frames, read them, check against spec
- Style philosophy: crafted, not generated

## Output Format

When reviewing, output:
1. `codex_review_applied: true`
2. `codex_fixes` array with specific, actionable items
3. For each fix: what beat, what's wrong, what to do instead
