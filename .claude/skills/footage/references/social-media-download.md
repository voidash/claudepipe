# Social Media Download Reference

## Platform Support Matrix

| Platform | Search | Download | Method | Reliability |
|----------|--------|----------|--------|-------------|
| YouTube | `ytsearch:` via yt-dlp | yt-dlp direct | Fully automated | High |
| TikTok | Playwright scrapes search page | yt-dlp `--impersonate chrome-131` | Automated | Medium (IP blocks possible) |
| Facebook | WebSearch finds URLs | yt-dlp with Googlebot UA | Semi-automated | Medium (only /posts/ URLs work) |
| Dailymotion | WebSearch finds URLs | yt-dlp direct | Automated | High |
| Instagram | Needs login cookies | yt-dlp `--cookies-from-browser` | Manual setup | Low |

## YouTube (Primary Source)

```bash
# Search
yt-dlp --dump-json --flat-playlist "ytsearch10:topic query"

# Download
yt-dlp -o "output.mp4" "URL"

# Download specific segment
yt-dlp --download-sections "*120-150" -o "clip.mp4" "URL"

# Transcript only (free — no video download)
yt-dlp --write-auto-subs --sub-lang ne,en --skip-download "URL"
```

## TikTok

**Search:** Playwright opens `https://www.tiktok.com/search?q=QUERY`, scrapes `a[href*="/video/"]` links. May show captcha but links are still extractable.

**Download:**
```bash
yt-dlp --impersonate chrome-131 -o "output.mp4" "https://www.tiktok.com/@user/video/ID"
```

**Known issues:**
- IP blocking is aggressive — `--impersonate` with curl_cffi required
- Search requires Playwright (no API, no yt-dlp search)
- Some videos are region-locked

**Dependencies:** `curl_cffi` must be installed for yt-dlp's Python version:
```bash
python3.14 -m pip install curl_cffi  # Match yt-dlp's Python
```

## Facebook (Googlebot Trick)

**CRITICAL: Use Googlebot user agent.** Facebook serves full OG metadata + video streams to Googlebot because they want content indexed by Google. Without it, you get login walls.

```bash
yt-dlp --user-agent "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" \
  -o "output.mp4" "URL"
```

**Only `/posts/` URL format works.** Other formats fail:

| URL format | Status |
|-----------|--------|
| `facebook.com/PAGE/posts/SLUG/ID/` | WORKS |
| `facebook.com/PAGE/videos/ID/` | FAILS (parser broken) |
| `facebook.com/reel/ID` | FAILS (parser broken) |
| `facebook.com/PROFILE/videos/ID/` | FAILS (parser broken) |

**Workaround for /videos/ and /reel/ URLs:**
1. Search the web for the same content in `/posts/` format
2. Or find the same content on TikTok/YouTube (Nepali content is usually cross-posted)
3. Last resort: user downloads from app

**Key Nepal Facebook Pages:**
- RONB (Routine of Nepal Banda): `facebook.com/RONBupdates`
- OnlineKhabar: `facebook.com/onaborjp`
- NEB Results: `facebook.com/nebresults`

## Dailymotion

Works out of the box — no special flags needed:
```bash
yt-dlp -o "output.mp4" "https://www.dailymotion.com/video/XXXX"
```

Nepali viral content often gets reposted here when removed from TikTok/Facebook.

## Download Priority Chain

When looking for a specific viral clip:
1. **YouTube** — search first, most reliable download
2. **TikTok** — search via Playwright, download with impersonation
3. **Facebook** — find `/posts/` URL via web search, download with Googlebot UA
4. **Dailymotion** — fallback, often has reposts
5. **Manual** — user downloads from app and drops into project

## Nepali Content Cross-Posting Pattern

Nepali news outlets (RONB, OnlineKhabar, Ekantipur) post the same content to:
- Their website (scrape with Playwright for screenshots/text)
- Facebook page (Googlebot trick for video)
- TikTok account (impersonation for download)
- YouTube channel (direct download)

When one platform fails, the same clip is almost always on another. Don't spend 10 minutes fighting Facebook when the same video is on TikTok.
