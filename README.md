# VoiceScope

**Speech-to-text with speaker diarization for YouTube content.**

VoiceScope downloads audio from YouTube, transcribes it with OpenAI Whisper, identifies who spoke when using PyAnnote speaker diarization, and produces a structured timeline of speaker-attributed text. Results are stored in Supabase and can be exported as JSON.

## Output

```json
[
  {
    "speaker": "Speaker 1",
    "start": 12.4,
    "end": 18.7,
    "text": "Welcome everyone to today's presentation."
  },
  {
    "speaker": "Speaker 2",
    "start": 19.0,
    "end": 26.3,
    "text": "Thanks for having me. I'm excited to be here."
  }
]
```

## Pipeline

```
YouTube URL
    │
    ▼
yt-dlp ──────────────► Download audio (WAV)
    │
    ▼
FFmpeg ──────────────► Resample to 16 kHz mono
    │
    ├──────────────────────────────────┐
    ▼                                  ▼
OpenAI Whisper                    PyAnnote Audio
(transcription)                   (speaker diarization)
    │                                  │
    └──────────────┬───────────────────┘
                   ▼
            Align & merge
           (overlap matching)
                   │
                   ▼
         Structured segments
                   │
                   ├──► JSON (stdout / file)
                   └──► Supabase (PostgreSQL)
```

## Requirements

- **Python** 3.10+
- **FFmpeg** (install via your package manager: `apt install ffmpeg`, `brew install ffmpeg`, etc.)
- **PyTorch** (installed automatically with the Python deps; CUDA recommended for GPU acceleration)
- **Supabase** project (free tier works)

## Setup

### 1. Clone & install

```bash
cd ~/Code/projects/voice-scope
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Supabase

Create a project at [supabase.com](https://supabase.com), then:

1. Go to **Project Settings → API** and copy your **Project URL** and **service\_role secret**.
2. Open the **SQL Editor**, paste the contents of `schema.sql`, and run it.

`schema.sql` creates a single table:

```sql
CREATE TABLE IF NOT EXISTS transcriptions (
    id           SERIAL PRIMARY KEY,
    url          TEXT NOT NULL,
    title        TEXT,
    duration     DOUBLE PRECISION,
    segments     JSONB NOT NULL DEFAULT '[]'::jsonb,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 3. Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...   # service_role key
HF_TOKEN=hf_your_token_here            # from https://huggingface.co/settings/tokens
WHISPER_MODEL=base                     # tiny, base, small, medium, large
SAMPLE_RATE=16000
DEVICE=cpu                             # or "cuda"
LOG_LEVEL=INFO
```

**HF\_TOKEN** is required — PyAnnote's diarization model is gated on Hugging Face. Visit [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) and accept the terms, then create a [user access token](https://huggingface.co/settings/tokens).

## Usage

### Single video

```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

Prints JSON to stdout.

### Batch processing — file of URLs

```bash
python main.py -f urls.txt
```

Format: one YouTube URL per line, blank lines ignored.

### Batch processing — multiple arguments

```bash
python main.py "https://youtube.com/watch?v=abc" "https://youtube.com/watch?v=xyz"
```

### Write output to a JSON file

```bash
python main.py "https://youtube.com/watch?v=abc" -o results.json
```

The file receives a JSON array of all results (one per URL).

### Skip database

```bash
python main.py "https://youtube.com/watch?v=abc" --no-save-db
```

Results are printed / written to `--output` but not persisted to Supabase.

## Project structure

```
voice-scope/
├── main.py          CLI entry point, argument parsing, orchestration
├── pipeline.py      Core pipeline: download → resample → transcribe → diarize → align
├── database.py      Supabase client wrapper (insert, query)
├── models.py        Data classes: Segment, TranscriptionResult
├── config.py        Environment-based configuration
├── schema.sql       One-time Supabase table setup
├── .env.example     Environment variable template
├── requirements.txt Python dependencies
├── __init__.py
└── README.md
```

## Architecture details

### Pipeline steps

| Step | Tool | Function | Retries |
|---|---|---|---|
| Download | yt-dlp | `download_audio()` | 3 attempts, expo backoff 4–30s |
| Resample | FFmpeg | `resample_audio()` | — |
| Transcribe | OpenAI Whisper | `transcribe()` | 2 attempts, expo backoff 2–10s |
| Diarize | PyAnnote Audio | `diarize()` | 2 attempts, expo backoff 2–10s |
| Align | custom overlap logic | `align()` | — |

### Alignment strategy

Each Whisper segment is assigned a speaker by measuring overlap with diarization turns. If a Whisper segment overlaps multiple diarization segments, the speaker with the greatest overlap duration wins. If no overlap exists (edge case), it defaults to `"Speaker 1"`. If diarization produces zero segments (e.g. a very short video), all text is attributed to `"Speaker 1"`.

### Error handling

- Each pipeline step has its own exception class (`DownloadError`, `TranscriptionError`, `DiarizationError`).
- Retries use **tenacity** with exponential backoff and jitter.
- Batch processing wraps each URL in a try/except — a single failure does not abort the rest of the batch.
- Database failures are logged and silently swallowed (the JSON output is still produced).

### Logging

Logs go to both stdout and `output/voicescope.log` with the format:

```
2026-06-04 14:30:01  INFO     pipeline  Downloading audio from https://...
2026-06-04 14:30:05  INFO     pipeline  Resampling ...
2026-06-04 14:30:10  INFO     pipeline  Transcribing ...
```

Control verbosity with `LOG_LEVEL` in `.env` (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

### Configuration

All config is driven by environment variables (loaded from `.env` by python-dotenv):

| Variable | Default | Description |
|---|---|---|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_KEY` | — | Supabase service\_role key |
| `HF_TOKEN` | — | Hugging Face access token |
| `WHISPER_MODEL` | `base` | Whisper model size |
| `DIARIZATION_MODEL` | `pyannote/speaker-diarization-3.1` | Diarization pipeline |
| `OUTPUT_DIR` | `./output` | Temp files and log destination |
| `SAMPLE_RATE` | `16000` | Resample target (Hz) |
| `DEVICE` | `cpu` | `cpu` or `cuda` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Model notes

- **Whisper** models range from `tiny` (fast, less accurate) to `large` (slow, most accurate). `base` is a good middle ground.
- **PyAnnote speaker-diarization-3.1** requires accepting terms of use on Hugging Face and providing `HF_TOKEN`.
- Whisper runs on CPU by default. Set `DEVICE=cuda` in `.env` for GPU acceleration (requires a CUDA-capable GPU and PyTorch compiled with CUDA).

## License

MIT
