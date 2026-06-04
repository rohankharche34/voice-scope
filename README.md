# VoiceScope

**Speech-to-text with speaker diarization for YouTube content.**

VoiceScope downloads audio from YouTube, transcribes it with OpenAI Whisper, identifies who spoke when using PyAnnote speaker diarization, and produces a structured timeline of speaker-attributed text. Results are stored in Supabase and can be exported as JSON.

## Output

```json
[
  {
    "speaker": "SPEAKER_00",
    "start": 12.4,
    "end": 18.7,
    "text": "Welcome everyone to today's presentation."
  },
  {
    "speaker": "SPEAKER_01",
    "start": 19.0,
    "end": 26.3,
    "text": "Thanks for having me. I'm excited to be here."
  }
]
```

Speaker labels (`SPEAKER_00`, `SPEAKER_01`, ...) come from PyAnnote's diarization model. For single-speaker content, all segments are labelled `SPEAKER_00`.

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
- **PyTorch** (installed automatically; CUDA recommended for GPU acceleration)
- **Supabase** project (free tier works)

## Setup

### 1. Clone & install

```bash
cd ~/Code/projects/voice-scope
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Accept Hugging Face model terms

PyAnnote's diarization pipeline and its sub-models are **gated** on Hugging Face. You must visit each of these pages and click **"Agree and access repository"**:

- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0
- https://huggingface.co/pyannote/speaker-diarization-community-1
- https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM

After accepting, create a [Hugging Face access token](https://huggingface.co/settings/tokens) with **Read access to contents of all public gated repos you can access** (fine-grained token). This goes in `HF_TOKEN`.

### 3. Supabase

Create a project at [supabase.com](https://supabase.com), then:

1. Go to **Project Settings → API** and copy your **Project URL** and **service\_role secret**.
2. Open the **SQL Editor**, paste the contents of `schema.sql`, and run it.

`schema.sql` creates a single table with the identity column pattern used by Supabase:

```sql
CREATE TABLE IF NOT EXISTS transcriptions (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url          TEXT NOT NULL,
    title        TEXT,
    duration     DOUBLE PRECISION,
    segments     JSONB NOT NULL DEFAULT '[]'::jsonb,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Required for the supabase-py service_role client:
GRANT ALL ON public.transcriptions TO service_role;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO service_role;
```

### 4. Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIs...     # service_role key
HF_TOKEN=hf_your_token_here               # Hugging Face token
WHISPER_MODEL=base                         # tiny, base, small, medium, large
SAMPLE_RATE=16000
DEVICE=cpu                                 # or "cuda"
LOG_LEVEL=INFO
```

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
├── main.py            CLI entry point, argument parsing, orchestration
├── pipeline.py        Core pipeline: download → resample → transcribe → diarize → align
├── database.py        Supabase client wrapper (insert, query via REST API)
├── models.py          Data classes: Segment, TranscriptionResult
├── config.py          Environment-based configuration (dotenv)
├── schema.sql         One-time Supabase table setup with GRANTs
├── .env.example       Environment variable template
├── .env               Your local configuration (git-ignored)
├── .gitignore         Ignores .env, __pycache__, .venv, output/, etc.
├── requirements.txt   Python dependencies
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

### Download

Uses a fixed output path (`audio.wav`) to avoid ambiguity with yt-dlp's `--print` behaviour. yt-dlp downloads the best audio stream and converts to WAV in one pass.

### Diarization

The pipeline loads `pyannote/speaker-diarization-3.1` via `Pipeline.from_pretrained()` with the `token` parameter (the `use_auth_token` kwarg was removed in recent versions).

The pipeline returns either:

- A `pyannote.core.Annotation` (legacy mode) — iterated with `.itertracks(yield_label=True)`
- A `DiarizeOutput` dataclass (newer versions) — the `Annotation` lives in `.speaker_diarization`

Both paths are handled transparently.

### Alignment strategy

Each Whisper segment is assigned a speaker by measuring overlap with diarization turns. If a Whisper segment overlaps multiple diarization segments, the speaker with the greatest overlap duration wins. If no overlap exists (edge case), it defaults to `"Speaker 1"`. If diarization produces zero segments (e.g. a very short video), all text is attributed to `"Speaker 1"`.

### Error handling

- Each pipeline step has its own exception class (`DownloadError`, `TranscriptionError`, `DiarizationError`).
- Retries use **tenacity** with exponential backoff and jitter.
- Batch processing wraps each URL in a try/except — a single failure does not abort the rest of the batch.
- Database failures (Supabase down, permission errors) are logged and silently swallowed — the JSON output is still produced.

### Logging

Logs go to both stdout and `output/voicescope.log`:

```
2026-06-04 14:30:01  INFO     pipeline  Downloading audio from https://...
2026-06-04 14:30:05  INFO     pipeline  Resampling ...
2026-06-04 14:30:10  INFO     pipeline  Transcribing ...
```

Control verbosity with `LOG_LEVEL` in `.env` (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

### Database

Uses the `supabase` Python client (`supabase-py`) over the REST API, not raw SQL. A singleton client is created with your `SUPABASE_URL` and `SUPABASE_KEY` (service\_role). The service\_role key bypasses Row Level Security, so RLS is left disabled. If you switch to an anon key, run:

```sql
ALTER TABLE transcriptions ENABLE ROW LEVEL SECURITY;
```

And add an appropriate policy.

### Configuration

All config is driven by environment variables (loaded from `.env` by python-dotenv):

| Variable | Default | Description |
|---|---|---|
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_KEY` | — | Supabase service\_role secret |
| `HF_TOKEN` | — | Hugging Face access token |
| `WHISPER_MODEL` | `base` | Whisper model size (tiny/base/small/medium/large) |
| `DIARIZATION_MODEL` | `pyannote/speaker-diarization-3.1` | Diarization pipeline |
| `OUTPUT_DIR` | `./output` | Temp files and log destination |
| `SAMPLE_RATE` | `16000` | Resample target (Hz) |
| `DEVICE` | `cpu` | `cpu` or `cuda` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## Troubleshooting

### 403 from Hugging Face when loading the diarization model

You haven't accepted the terms for one of the gated models. Visit each of these and click "Agree and access repository":

- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0
- https://huggingface.co/pyannote/speaker-diarization-community-1
- https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM

### "permission denied for table transcriptions" from Supabase

The service\_role needs explicit grants. Run this in your Supabase SQL Editor:

```sql
GRANT ALL ON public.transcriptions TO service_role;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO service_role;
```

### "Downloaded file not found"

If yt-dlp downloads but the WAV is not found, you may be hitting a rate limit or geo-block. The pipeline retries 3 times with backoff. Check `output/voicescope.log` for the full yt-dlp stderr output.

## Model notes

- **Whisper**: models range from `tiny` (fast, less accurate) to `large` (slow, most accurate). `base` is a good middle ground. First run downloads the model weights (~139 MB for `base`).
- **PyAnnote speaker-diarization-3.1**: requires accepting terms on Hugging Face for 4 separate gated repos. The pipeline downloads weights on first run (~33 MB total).
- **Device**: both Whisper and PyAnnote run on CPU by default. Set `DEVICE=cuda` in `.env` for GPU acceleration (requires a CUDA-capable GPU and PyTorch compiled with CUDA).

## License

MIT
