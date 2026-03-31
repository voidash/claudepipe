# Clip Acquisition Pipeline

Transcript-based video clip search with timestamp extraction. Ensures we get the RIGHT 3-5 seconds from the RIGHT video, not the first YouTube result.

## Why Blind Search Fails

`ytsearch1:Balen bulldozer` returns the first result — usually a news commentary video ABOUT the event, not the actual footage. You get a talking head saying "Balen used bulldozers" instead of actual bulldozer footage.

For a 30-minute documentary, you need 60-100 clip segments. Each one must show the SPECIFIC visual the script calls for. Blind download wastes time and produces unusable clips.

## The Pipeline (per clip)

### Step 1: Search broadly

```bash
yt-dlp --dump-json --flat-playlist "ytsearch8:QUERY" --no-download
```

Get 8 candidates. Record title, duration, URL, channel. Prefer:
- News channels over commentary channels
- Shorter videos (more likely raw footage) over 30+ min compilations
- Nepali-language results for Nepal footage (original, not repackaged)

### Step 2: Pull transcripts (free, no download)

```bash
for url in CANDIDATES:
    yt-dlp --write-auto-subs --sub-lang ne,en --skip-download -o "tmp/%(id)s" "$url"
```

This costs nothing — no video downloaded, just subtitle files.

### Step 3: Claude reads transcripts to find the moment

Claude reads the subtitle files and identifies:
- **Which video** has the content we need (not just mentions it — actually SHOWS it)
- **What timestamp** the relevant moment occurs at
- **How long** the useful segment is (usually 3-10 seconds)

Example: Script says "police fired tear gas into the hospital."
- Video A transcript: "...and then the police moved to the hospital area..." at 2:45
- Video B transcript: (raw footage, no narration, just timestamps showing hospital at 1:30-1:55)
- Video C transcript: "In this video we see the hospital footage..." at 5:20 (commentary over footage)

Choose Video B (raw footage) or Video C (has the actual footage even if narrated over).

### Step 4: Download only the segment

```bash
yt-dlp -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]" \
  --merge-output-format mp4 \
  --download-sections "*START-END" \
  -o "assets/clips/CLIP_NAME.mp4" \
  "URL"
```

`--download-sections "*120-135"` downloads only seconds 120-135. No wasting bandwidth on full videos.

### Step 5: Verify the clip

Render a still frame from the downloaded clip:
```bash
ffmpeg -i clip.mp4 -ss 2 -frames:v 1 -q:v 2 clip_preview.jpg
```

Claude reads the preview image to verify:
- Does it show what the script describes?
- Is it actual footage or a title card/commentary frame?
- Is the resolution acceptable?
- Are there watermarks or overlays that make it unusable?

If the preview fails, go back to Step 3 with the next candidate.

### Step 6: Log the source

Save to `assets/clips/clip_log.json`:
```json
{
  "clip_name": "hospital_teargas",
  "source_url": "https://youtube.com/watch?v=...",
  "source_channel": "Kantipur TV",
  "segment": "1:30-1:55",
  "description": "Raw footage of police outside Civil Service Hospital with tear gas visible",
  "verified": true
}
```

## Clip Count by Act

A 30-minute JH-style documentary needs ~60-100 clip segments:

| Act | Duration | Clips needed | Types |
|-----|----------|-------------|-------|
| Cold Open | 2:30 | 8 | TikToks, Instagram posts, news headlines, platform logos |
| Act 1: Five Days | 5:30 | 15 | Protest footage (multi-angle, multi-city), Discord, hospital, parliament |
| Act 2: Landslide | 3:00 | 10 | Balen montage (4 eras), campaign, election day, results, celebration |
| Act 3: Pattern | 8:00 | 12 | Archival: Chavez, Orban, Erdogan, Gezi Park, Five Star (4 countries) |
| Act 4: Constitution | 9:00 | 10 | Parliament session, bulldozer ops, vendor confrontations, blockade, BRI |
| Act 5: Fork | 3:00 | 5 | Callback montage, Nepal landscape, parliament building |
| **Total** | **31:00** | **~60** | |

## TikTok Clips

For TikTok (NepoKids trend, viral clips):
1. Search via Playwright: `https://www.tiktok.com/search?q=QUERY`
2. Scrape video URLs from results
3. Download with: `yt-dlp --impersonate chrome-131 -o OUTPUT URL`
4. TikTok clips are already short (15-60s) — usually don't need segment extraction

## Archival Footage (Act 3)

For historical clips (Chavez 1998, Orban 2010, Erdogan 2002):
- Search YouTube with year + event specifics: `"Chavez 1998 election victory speech"`
- Prefer news archive channels (AP Archive, British Pathé, Reuters) — they have the original footage
- Archival clips need B&W or vintage treatment in Remotion — the download is just the source

## Quality Standards

Every clip must pass before being marked "ready":
- [ ] Shows what the script describes (not just mentions it)
- [ ] Actual footage, not a still image with Ken Burns
- [ ] Resolution >= 480p (720p preferred)
- [ ] No hard-burned subtitles covering the visual (soft subs OK)
- [ ] No channel watermarks in the center of the frame (corner watermarks acceptable)
- [ ] Duration matches the script need (not a 10-minute video when we need 5 seconds)
- [ ] Source logged in clip_log.json with URL, channel, segment times

## What NOT to Download

- Full documentaries about the topic (we're making our own)
- Commentary/reaction videos (we need the footage they're reacting to)
- Compilation videos (hard to extract clean segments, usually have music overlays)
- Videos with thick watermarks or heavy post-processing
- Re-uploads of the same footage from smaller channels (prefer the original source)
