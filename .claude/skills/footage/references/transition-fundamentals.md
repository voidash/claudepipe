# Transition Fundamentals (from AE tutorial)

## Core Principles

**Pace**: Speed of movement — slow, fast, anything in between.
**Rhythm**: Regularity of set movement.
These two together make transitions feel dynamic. Without them, transitions feel flat.

## Rules

1. **Cut into the movement** — the cut happens where the MOST movement is, not at rest
2. **Easing is mandatory** — no linear movement, ever. Anticipation → action → settle.
3. **Grounded in reality** — the more animations follow real physics, the better they feel
4. **Contrast drives hard cuts** — light→dark, color→opposite color, busy→empty
5. **1-2 frame invert stutter** — apply invert effect on an adjustment layer for 1-2 frames at the cut point. Makes it look super clean.
6. **Momentum carries attention** — movement direction before the cut should match movement direction after the cut

## Transition Types (ranked by use case)

### 1. Hard Cut
- Most overlooked, especially in animation
- Works best with CONTRAST: light→dark, color shifts, busy→clean
- Don't overthink it — most of the time a hard cut with good pacing is enough

### 2. Movement Transition
- Use movement to drive momentum and attention
- Classic in 2D animation
- The movement itself IS the transition — no fancy overlay needed

### 3. Match Cut (most versatile)
Four variants:

**Asset Match Cut**: Same element (word, logo, shape) stays in the same position across both shots. Grid-align the anchor point.

**Position Match Cut**: Two shots moving in the SAME DIRECTION. Cut at peak movement. Easing critical — cut where velocity is highest.

**Scale Match Cut**: Zoom in on shot A → cut → zoom out from shot B (or vice versa). Cut in the middle of the scale change. Add blur to blend.

**Rotation Match Cut**: Best with circular objects. Center the focal point, animate rotation, cut mid-rotation. Objects MUST be perfectly centered or they wobble.

## Implementation for Remotion

### What we should be doing:
- **TH → Song**: Scale match cut. Zoom into TH face → white/blur → zoom out from song footage. Cut at peak zoom.
- **Song → next TH**: Position match cut. Song footage moving in a direction → cut → TH arriving from same direction.
- **Rugpull moments**: Hard cut with contrast (1-2 frame invert stutter) + glitch
- **Every transition**: Must have easing. Use `spring()` or custom bezier, never linear.

### The 1-2 frame invert trick:
At the exact cut frame, render 1-2 frames with `filter: invert(1)` on the outgoing shot. This creates a subliminal flash that makes cuts feel intentional and clean.

### Pacing rule:
- Talking head sections: slower transitions (8-10 frames)
- Song/music sections: faster transitions (4-6 frames)
- Rugpull reveals: instant (2-3 frames) with contrast
