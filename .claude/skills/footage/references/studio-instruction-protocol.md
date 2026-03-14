# Studio Instruction Protocol

How Claude interprets markers, instructions, and edit operations from the studio's `edit_manifest.json`. This is the reference for both the post-session processor (Phase 12) and parallel agents (Phases 13-15).

## Marker Semantics

Markers are placed by the user in the studio. They carry positional and temporal information about specific points in the footage.

```json
{
  "id": "m1",
  "name": "transition point",
  "time": 15.3,
  "frame_number": 459,
  "position": {"x": 0.6, "y": 0.3},
  "type": "spatial",
  "source_clip_id": "clip_003"
}
```

### Spatial markers (`type: "spatial"`)
- Have `position.x` and `position.y` — normalized coordinates (0.0 to 1.0) on the video frame
- Mean: "this point in the video, at this screen location, at this time is significant"
- Used for: overlay placement, in-video component positioning, transition origin points

### Temporal markers (`type: "temporal"`)
- Have `position: null` — time-only, no screen location
- Mean: "this moment in time is significant"
- Used for: cut points, split points, transition boundaries, SFX placement

## Instruction Interpretation

The user writes free-text instructions in the per-unit textarea. Claude reads these from `edit_manifest.units[unitId].instructions`. Instructions reference markers by ID (m1, m2, etc.).

### "Put a transition at m1"

1. Look up m1's `time` and `source_clip_id` in the unit's markers
2. Identify what content exists BEFORE m1's timestamp — read the clip's transcript, vision analysis, and activity classification for the segment ending at m1
3. Identify what content exists AFTER m1's timestamp — same analysis for the segment starting at m1
4. Choose a transition type that connects the two pieces contextually:
   - Topic shift → crossfade or fade-to-black
   - Same topic, different angle → cut or dissolve
   - Energy change → wipe or motion-based transition
5. If m1 is spatial: the transition can originate from the marker's (x, y) position (e.g., a radial wipe from that point)
6. Generate the transition (if it requires a generated clip, e.g., a Remotion motion graphic):
   - Create the transition as a clip on the `overlay` track
   - Position it at m1's timeline time
   - Duration: typically 0.3-1.0 seconds centered on m1's time
7. Register the transition in `timeline.transitions[]` with `from_clip` and `to_clip` references
8. Write back to the unit's manifest and report what was done

### "Add animation at m1"

1. Look up m1's marker data
2. If spatial: the animation is positioned at (x, y) as an overlay on the footage
   - Create an `overlay` track clip at m1's timeline position
   - Set `transform.x` and `transform.y` from marker position
   - Scale as appropriate for the content
3. If temporal: the animation is inserted at that time point (replacing or overlaying footage)
4. Check the unit's `needs_animation` flag and `added_media` for reference material
5. Generate the animation (Manim or Remotion) per Phase 13
6. Add the rendered animation to `timeline.tracks[overlay].clips[]`

### "Split at m1"

1. Look up m1's `time` and `source_clip_id`
2. Find the timeline clip that contains m1's time
3. Create a split in `edit_manifest.units[unitId].clip_edits`:
   ```json
   {"at": 15.3, "produces": ["tc_001a", "tc_001b"]}
   ```
4. The first piece (tc_001a) gets `out_point = 15.3`, the second (tc_001b) gets `in_point = 15.3`
5. Transcript segments divide at the split point — segments before 15.3 go to tc_001a, after to tc_001b
6. Both pieces remain in the same unit unless the user drags one to a different unit

### "Break this unit into two"

1. Read the unit's transcript content
2. Identify the natural topic boundary — where does the subject matter change?
   - Look for: silence gaps > 2s, topic keyword shifts, activity type changes, scene boundaries
3. If unclear, ask the user where to split
4. Create a split at the topic boundary timestamp
5. Create a new unit group in `timeline.unit_groups[]` for the second half
6. Move the second-half clips to the new unit
7. Create a new unit directory mirroring the main project structure
8. Update `edit_manifest.unit_order` to include the new unit

### "Delete from X to Y" or "Cut the dead air around 0:32"

1. Identify the time range to remove
2. Add to `edit_manifest.units[unitId].clip_edits[clipId].deleted_ranges`:
   ```json
   {"start": 30.0, "end": 37.0, "reason": "dead air"}
   ```
3. The clip is NOT physically modified — the deleted range is metadata
4. Phase 18 validation ensures no timeline reference uses content from deleted ranges
5. FCPXML exporter skips deleted ranges when building the output timeline

## Edit Operations Data Model

### Trim

Non-destructive in/out point adjustment. The original range is always preserved.

```json
"clip_edits": {
  "tc_001": {
    "trim": {
      "in": 5.0,      // new in point (seconds)
      "out": 23.5     // new out point (seconds)
    }
  }
}
```

The global timeline clip's `in_point` and `out_point` are updated to match. The `trim.original_in` and `trim.original_out` on the timeline clip preserve the original range for undo.

### Split

Divides one timeline clip into two independent pieces.

```json
"clip_edits": {
  "tc_001": {
    "splits": [
      {"at": 18.0, "produces": ["tc_001a", "tc_001b"]}
    ]
  }
}
```

After split:
- `tc_001a`: `in_point = original_in, out_point = 18.0`
- `tc_001b`: `in_point = 18.0, out_point = original_out`
- Both reference the same `source_clip_id`
- Both can be independently trimmed, moved, or deleted
- Transcript segments are divided at the split point (time-based, no re-ASR)

### Delete Range

Marks a time range within a clip as deleted. Recoverable.

```json
"clip_edits": {
  "tc_001": {
    "deleted_ranges": [
      {"start": 12.0, "end": 15.0, "reason": "dead air"}
    ]
  }
}
```

### Move Between Units

Records a clip being dragged from one unit to another.

```json
"clip_moves": [
  {
    "clip_id": "tc_001b",
    "from_unit": "unit_001_intro",
    "to_unit": "unit_003_demo",
    "moved_at": "2026-03-14T11:25:00Z"
  }
]
```

The clip's `unit_id` in the global timeline is updated to reflect the move.

## Enforcement Chain

```
Studio UI (user edits)
    → edit_manifest.json (stores edits as data)
    → Phase 12 post-session (applies edits to global timeline)
    → Phase 18 validation (verifies all constraints, REJECTS violations)
    → Phase 17 exporter (reads validated global timeline, produces FCPXML/Blender)
```

At no point does Claude directly modify the exporter. Claude writes to the edit_manifest and footage_manifest. The exporter is a deterministic script that reads the final state. Trim enforcement is in the exporter AND in Phase 18 validation — double protection.

## Versioning

Each studio sync auto-commits `edit_manifest.json` to git:
```bash
git add edit_manifest.json && git commit -m "studio sync $(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

- Current version = HEAD of edit_manifest.json
- Previous versions = git log of edit_manifest.json
- Restore = `git checkout <commit> -- edit_manifest.json`
- Studio shows current version as default, previous versions as expandable history
- Per-unit: the active clips/edits are whatever the current edit_manifest says
