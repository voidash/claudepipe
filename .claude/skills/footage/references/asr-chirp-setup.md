# ASR Setup for Nepali + English Code-Switching

## Audio Requirements

All ASR engines expect: **16kHz mono WAV**. The pipeline extracts at 48kHz for DeepFilterNet denoising, then downsamples to 16kHz for ASR. Ensure audio extraction (Phase 3) runs before any transcription step.

## Primary (Recommended): Google Chirp 2

**Status: INSTALLED and operational.** Used as the primary ASR path for precise word-level timestamps.

### Setup (Already Done)

- **Package:** `google-cloud-speech` (installed via `pip install google-cloud-speech`)
- **GCP Project:** `agentshakti` (project ID: `agentshakti`, project number: `580184833052`)
- **Billing:** Enabled on `agentshakti`
- **API:** Cloud Speech-to-Text API enabled
- **Service Account:** `claudepipe-stt@agentshakti.iam.gserviceaccount.com` (roles: `speech.client`, `speech.admin`)
- **Credentials file:** `~/footage/gcp-stt-key.json`

### Environment Variable

Must be set before running transcription:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/footage/gcp-stt-key.json
```

Add this to your shell profile (`.zshrc` / `.bashrc`) for persistence.

### Regional Availability

Chirp 2 is ONLY available in these 3 locations:
- `us-central1` (GA) — **use this one**
- `europe-west4` (GA)
- `asia-southeast1` (GA)

**Important constraints:**
- Multi-language codes (e.g., `["ne-NP", "en-US"]`) require `eu`, `global`, or `us` locations — but Chirp 2 does NOT exist in those locations. Therefore **multi-language codes cannot be used with Chirp 2**.
- Use single language code `["ne-NP"]` instead. Chirp 2 handles English code-switching adequately with just the Nepali code.
- `language_codes=["auto"]` is unreliable for Nepali (detected as Latin in testing).

### Sync Recognize Limits

- **Maximum duration:** 60 seconds per request
- For clips > 55s: split into chunks (52s with 3s overlap), transcribe each, merge by deduplicating overlap words
- For clips > 8 hours: use BatchRecognize (requires GCS upload)

### Usage

```python
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
from google.api_core.client_options import ClientOptions

# Must use regional endpoint for us-central1
client = SpeechClient(
    client_options=ClientOptions(
        api_endpoint="us-central1-speech.googleapis.com"
    )
)

with open("audio.wav", "rb") as f:
    audio_bytes = f.read()

config = cloud_speech.RecognitionConfig(
    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
    language_codes=["ne-NP"],  # Single code only — multi-language not supported here
    model="chirp_2",
    features=cloud_speech.RecognitionFeatures(
        enable_word_time_offsets=True,
        enable_word_confidence=True,
    ),
)

request = cloud_speech.RecognizeRequest(
    recognizer="projects/agentshakti/locations/us-central1/recognizers/_",
    config=config,
    content=audio_bytes,
)

response = client.recognize(request=request)
for result in response.results:
    alt = result.alternatives[0]
    print(f"Lang: {result.language_code}, Text: {alt.transcript}")
    for w in alt.words:
        print(f"  [{w.start_offset.total_seconds():.2f}-{w.end_offset.total_seconds():.2f}] {w.word}")
```

### Advantages Over Gemini

- Native word-level timestamps with high accuracy
- Better punctuation and sentence boundary detection
- Consistent timing (Gemini timestamps are approximate ±0.3s)

### Drawbacks

- Higher latency for long files
- 60s sync limit requires chunking
- Single language code only (no explicit multi-language)
- Costs money per minute of audio (see [pricing](https://cloud.google.com/speech-to-text/pricing))

## Secondary: Google Gemini

**Status: INSTALLED and operational.** Use when approximate timestamps are acceptable or as fallback.

Gemini handles Nepali well and supports code-switching between Nepali and English natively.

### Configuration

- Uses `google.genai` client library (already installed)
- Authenticates via `GOOGLE_API_KEY` or `GEMINI_API_KEY` environment variable
- No service account or credentials file required

### Limitations

- **No native word-level timestamps.** Word timing is obtained via prompt engineering — instruct the model to return timestamps in the response. This means timestamps are approximate (typically within ±0.3s) rather than exact.
- **File size limit:** Files larger than **20MB** must be split into chunks before sending.

### Chunking Strategy

For files exceeding 20MB, split into approximately **10-minute chunks** with a small overlap (2-3 seconds) to avoid cutting words at boundaries. Reassemble transcripts by deduplicating the overlap region using timestamp alignment.

## Last Resort: OpenAI Whisper

**Status: NOT INSTALLED. Not recommended.**

### Setup

```bash
pip install openai-whisper
```

### Why to Avoid

- **Nepali word error rate (WER) is ~40%+**, making transcripts unreliable for downstream processing
- Code-switching between Nepali and English is handled poorly — the model tends to commit to one language per segment
- Requires significant local compute (GPU recommended) for reasonable speed

### When to Use

Only if no API keys are available and offline-only transcription is required. Use the `large-v3` model for the least-bad Nepali results:

```python
import whisper

model = whisper.load_model("large-v3")
result = model.transcribe(
    "audio.wav",
    language="ne",
    task="transcribe"
)
```

Even with `large-v3`, expect to manually correct a substantial portion of the output.

## Decision Flowchart

1. Is `GOOGLE_APPLICATION_CREDENTIALS` set and `google-cloud-speech` installed? **Use Chirp 2.** (best word-level timestamps)
2. Is `GEMINI_API_KEY` or `GOOGLE_API_KEY` set? **Use Gemini.** (approximate timestamps, good code-switching)
3. Is `openai-whisper` installed? **Use Whisper with a warning.**
4. Else, **fail with an error** listing the setup options.
