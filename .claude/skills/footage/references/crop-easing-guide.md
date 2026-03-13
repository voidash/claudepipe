# 9:16 Crop Strategies and Easing Curves Reference

## Crop Math

Source resolution: **1920x1080** (16:9 landscape).
Target aspect: **9:16 portrait** displayed at 1080x1920.

The crop window on the source frame is **608px wide** (1080 * 9/16 = 607.5, rounded to 608) by **1080px tall** (full height).

Blender crop values represent pixels removed from each edge:

```
min_x + visible_width + max_x = 1920
min_x + 608 + max_x = 1920
min_x + max_x = 1312
```

- `min_x` range: **0 to 1312** (pixels cropped from left)
- `max_x` range: **1312 to 0** (pixels cropped from right)
- `min_x = 0`: crop window at far left
- `min_x = 656`: crop window centered
- `min_x = 1312`: crop window at far right

The crop window slides horizontally. `min_y` and `max_y` stay at **0** (full height used).

## Easing Curves

**NEVER use LINEAR easing.** Linear interpolation creates robotic, unnatural movement that looks like a surveillance camera pan. Always select from the following:

### When to Use Each Easing

| Easing | Feel | Use Case |
|---|---|---|
| **BEZIER** | Smooth, general-purpose | Default choice. Works for most crop movements between speakers or subjects. |
| **SINE** | Gentle, organic | Transitions between calm segments. Conversations, interviews, slow pans. |
| **EXPO** | Dramatic snap | Action moments, quick cuts, moving to catch a sudden gesture or reaction. |
| **BACK** | Slight overshoot | Emphasis points. The crop slides past the target then settles back, adding a playful feel. |
| **ELASTIC** | Bouncy, spring-like | Speaker gestures, energetic moments. The crop wobbles around the target before resting. |
| **BOUNCE** | Impact, gravity-like | Scene changes, subject entering frame. Feels like the crop "lands" at its destination. |
| **CONSTANT** | No movement | Stationary subject, single speaker who isn't moving. Holds position until the next keyframe. |

### Easing Direction

Each easing type combines with a direction:

- **EASE_IN**: slow start, fast end
- **EASE_OUT**: fast start, slow end (most natural for "arriving" at a subject)
- **EASE_IN_OUT**: slow start and end, fast middle (best default for most movements)

## Blender Interpolation Mapping

```python
# Set on each keyframe_point in the FCurve
kp.interpolation = 'BEZIER'    # or 'SINE', 'EXPO', 'BACK', 'ELASTIC', 'BOUNCE', 'CONSTANT'
kp.easing = 'EASE_IN_OUT'      # or 'EASE_IN', 'EASE_OUT'
```

Recommended defaults per easing type:

| Easing Type | Default Direction |
|---|---|
| BEZIER | EASE_IN_OUT |
| SINE | EASE_IN_OUT |
| EXPO | EASE_OUT |
| BACK | EASE_OUT |
| ELASTIC | EASE_OUT |
| BOUNCE | EASE_OUT |
| CONSTANT | (direction ignored) |

## Movement Constraints

### Minimum Movement Threshold

**Do not create keyframes for movements smaller than 20 pixels.** Small adjustments create visible micro-jitter without meaningful reframing. If the computed crop shift is under 20px, skip the keyframe and hold the previous position.

### Maximum Speed

**Cap movement at 800 pixels per second.** At 30fps, that is ~27 pixels per frame. Faster pans cause motion blur and feel jarring on mobile screens.

To calculate speed:

```
speed_px_per_sec = abs(new_min_x - old_min_x) / (frame_duration / fps)
```

If speed exceeds 800 px/s, either:
1. Extend the transition duration (add more frames between keyframes), or
2. Insert an intermediate keyframe to split the movement into two stages.

### Smoothing Window

Apply a **0.5-second smoothing window** (15 frames at 30fps) when converting detected subject positions to crop keyframes. This prevents jitter from noisy detection data. Average the target `min_x` values across the window before committing keyframes.

## Practical Patterns

**Static speaker, centered**: Set `min_x = 656`, `max_x = 656`, use CONSTANT. No keyframes needed beyond the initial position.

**Two speakers alternating**: Place keyframes at each speaker change. Use SINE/EASE_IN_OUT for calm conversations, EXPO/EASE_OUT for rapid back-and-forth.

**Speaker walking across frame**: Continuous tracking. Place keyframes every 1-2 seconds following the subject. Use BEZIER/EASE_IN_OUT for fluid motion.

**Dramatic reveal / reaction cut**: Use BACK/EASE_OUT for overshoot effect, or BOUNCE/EASE_OUT for impact landing at the new subject.

**High-energy montage**: Mix ELASTIC and EXPO for variety. Keep transitions short (10-15 frames).
