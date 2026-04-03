# Animation Style Configuration

Reference for maintaining visual consistency across all generated animations (Manim, Remotion, Blender overlays).

## style_config.json

Lives at the project root. Copied from a template during project initialization. Every animation generation step MUST read this file and apply its values. Never hardcode colors, fonts, or dimensions.

### Color palette

```json
{
  "colors": {
    "primary": "#HEXCODE",
    "secondary": "#HEXCODE",
    "accent": "#HEXCODE",
    "background": "#HEXCODE",
    "text": "#HEXCODE"
  }
}
```

- `primary` — used for highlights, emphasized text, key diagram elements.
- `secondary` — used for supporting elements, secondary labels.
- `accent` — used for call-to-action elements, annotations, arrows.
- `background` — scene background color for all animations.
- `text` — default text color.

### Typography

```json
{
  "typography": {
    "heading": { "font": "Inter", "weight": 700, "size": 48 },
    "body": { "font": "Inter", "weight": 400, "size": 32 },
    "code": { "font": "JetBrains Mono", "weight": 400, "size": 28 },
    "nepali": { "font": "Noto Sans Devanagari", "weight": 400, "size": 32 }
  }
}
```

When rendering Nepali text, always use the `nepali` font entry. Devanagari glyphs will not render correctly with Latin-only fonts. Detect Nepali content by checking the manifest's `language` field or the presence of Devanagari Unicode characters (U+0900-U+097F).

### Manim settings

```json
{
  "manim": {
    "background_color": "#HEXCODE",
    "text_color": "#HEXCODE",
    "quality": "high_quality",
    "fps": 30,
    "pixel_width": 1920,
    "pixel_height": 1080
  }
}
```

Apply `background_color` via `config.background_color`. Set frame rate and resolution to match the project output format. For 9:16 shorts, swap width and height (1080x1920).

### Remotion settings

```json
{
  "remotion": {
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "spring_config": {
      "damping": 15,
      "mass": 1,
      "stiffness": 120
    }
  }
}
```

Use `spring_config` values for all transition animations in Remotion compositions. This keeps motion feel consistent across the project.

## Applying the config

When generating any animation:

1. Read `style_config.json` from the project root. Fail explicitly if the file is missing.
2. Use `colors.primary` for highlights and emphasis.
3. Use `colors.background` for scene backgrounds.
4. Use the correct typography entry for the content type (heading, body, code, nepali).
5. Match `fps` to the project fps (30).
6. Match resolution to the output format: 1920x1080 for 16:9, 1080x1920 for 9:16.
7. Never override these values with defaults or hardcoded alternatives.
