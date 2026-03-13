# ASR Setup for Nepali + English Code-Switching

## Audio Requirements

All ASR engines expect: **16kHz mono WAV**. The `extract_audio.py` script handles conversion from source video. Ensure audio extraction runs before any transcription step.

## Primary (Recommended): Google Gemini

**Status: INSTALLED and operational.** Used as the primary ASR path.

Gemini handles Nepali well and supports code-switching between Nepali and English natively. No additional package installation is needed.

### Configuration

- Uses `google.genai` client library (already installed)
- Authenticates via `GOOGLE_API_KEY` or `GEMINI_API_KEY` environment variable
- No service account or credentials file required

### Limitations

- **No native word-level timestamps.** Word timing is obtained via prompt engineering — instruct the model to return timestamps in the response. This means timestamps are approximate (typically within +/- 0.3s) rather than exact.
- **File size limit:** Files larger than **20MB** must be split into chunks before sending.

### Chunking Strategy

For files exceeding 20MB, split into approximately **10-minute chunks** with a small overlap (2-3 seconds) to avoid cutting words at boundaries. Reassemble transcripts by deduplicating the overlap region using timestamp alignment.

## Fallback: Google Chirp 2

**Status: NOT INSTALLED.** Use only if Gemini is unavailable or if precise word-level timestamps are required.

### Setup

```bash
pip install google-cloud-speech
```

Requires a Google Cloud service account with the Speech-to-Text API enabled.

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/to/service-account.json"
```

### Configuration

```python
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech

client = SpeechClient()

config = cloud_speech.RecognitionConfig(
    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
    language_codes=["ne-NP", "en-US"],
    model="chirp_2",
)

request = cloud_speech.RecognizeRequest(
    recognizer="projects/{project}/locations/global/recognizers/_",
    config=config,
    content=audio_bytes,  # or use uri for GCS
)

response = client.recognize(request=request)
```

### Advantages Over Gemini

- Native word-level timestamps with high accuracy
- Better punctuation and sentence boundary detection
- Streaming support for real-time use cases

### Drawbacks

- Requires GCP project setup, billing, and service account management
- Higher latency for long files
- Additional dependency to install and maintain

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

1. Is `GOOGLE_API_KEY` or `GEMINI_API_KEY` set? **Use Gemini.**
2. Else, is `GOOGLE_APPLICATION_CREDENTIALS` set and `google-cloud-speech` installed? **Use Chirp 2.**
3. Else, is `openai-whisper` installed? **Use Whisper with a warning.**
4. Else, **fail with an error** listing the setup options.
