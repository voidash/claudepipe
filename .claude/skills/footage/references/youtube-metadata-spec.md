# YouTube Upload Metadata

Reference for structuring YouTube metadata for both long-form videos and shorts.

## Required Fields

| Field | Constraint |
|-------|-----------|
| `title` | Max 100 characters. Front-load keywords. No clickbait that misrepresents content. |
| `description` | No hard limit, but first 150 characters appear in search results. Include chapters if applicable. |
| `tags` | Array of strings. Include topic keywords, language, and series name if applicable. |
| `category_id` | Integer. See common IDs below. |
| `language` | BCP-47 language code for the video's primary spoken language. |

## Common Category IDs

| ID | Category |
|----|----------|
| 22 | People & Blogs |
| 25 | News & Politics |
| 27 | Education |
| 28 | Science & Technology |

## Chapters

Chapters are defined as timestamps in the description body.

- First chapter must start at `0:00`.
- Minimum duration per chapter is **10 seconds**.
- Format: `0:00 Introduction` (one per line, timestamp then title).
- YouTube requires at least 3 chapters for the feature to activate.

## Shorts Metadata

- Title: max 100 characters. Include 1-2 relevant hashtags (e.g., `#coding #nepal`).
- Description: keep it brief (1-2 sentences). Hashtags can also go here.
- Tags and category follow the same rules as long-form.

## Privacy

Always default to **"private"**. The user publishes manually through YouTube Studio. Never set a video to public or unlisted programmatically unless the user explicitly requests it.

## Language Codes

| Code | Language |
|------|----------|
| `ne` | Nepali |
| `en` | English |

Set the language code based on the manifest's `language` field.

## Manifest Storage

YouTube metadata is stored in the manifest under `youtube`:

```json
{
  "youtube": {
    "long_form": {
      "title": "...",
      "description": "...",
      "tags": [],
      "category_id": 27,
      "language": "ne",
      "privacy": "private",
      "chapters": []
    },
    "shorts": [
      {
        "short_id": "short_01",
        "title": "...",
        "description": "...",
        "tags": [],
        "category_id": 27,
        "language": "ne",
        "privacy": "private"
      }
    ]
  }
}
```
