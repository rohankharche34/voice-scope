from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import torch
import whisper
from config import config
from models import Segment, TranscriptionResult
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


class DownloadError(PipelineError):
    pass


class TranscriptionError(PipelineError):
    pass


class DiarizationError(PipelineError):
    pass


# ---------------------------------------------------------------------------
# Step 1 – Download audio from YouTube
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(DownloadError),
    reraise=True,
)
def download_audio(url: str, output_dir: Path) -> Path:
    raw_path = output_dir / "audio.%(ext)s"
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", str(raw_path),
        "--print", "filename",
        url,
    ]
    logger.info("Downloading audio from %s", url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise DownloadError(f"yt-dlp failed: {result.stderr.strip()}")
    audio_path = Path(result.stdout.strip())
    if not audio_path.exists():
        raise DownloadError(f"Downloaded file not found: {audio_path}")
    logger.info("Downloaded audio to %s", audio_path)
    return audio_path


# ---------------------------------------------------------------------------
# Step 2 – Resample to 16 kHz mono WAV
# ---------------------------------------------------------------------------

def resample_audio(src: Path, dst: Path) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-ar", str(config.sample_rate),
        "-ac", "1",
        str(dst),
    ]
    logger.info("Resampling %s -> %s (%s Hz, mono)", src, dst, config.sample_rate)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise PipelineError(f"FFmpeg failed: {result.stderr.strip()}")
    logger.info("Resampled audio to %s", dst)
    return dst


# ---------------------------------------------------------------------------
# Step 3 – Whisper transcription
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(TranscriptionError),
    reraise=True,
)
def transcribe(audio_path: Path) -> dict:
    logger.info("Loading Whisper model '%s' on %s", config.whisper_model, config.whisper_device)
    model = whisper.load_model(config.whisper_model, device=config.whisper_device)
    logger.info("Transcribing %s ...", audio_path)
    result = model.transcribe(str(audio_path), verbose=False)
    if "segments" not in result:
        raise TranscriptionError("Whisper returned no segments")
    logger.info("Whisper produced %d segments", len(result["segments"]))
    return result


# ---------------------------------------------------------------------------
# Step 4 – Speaker diarization (pyannote)
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    retry=retry_if_exception_type(DiarizationError),
    reraise=True,
)
def diarize(audio_path: Path) -> list[dict]:
    logger.info("Loading diarization pipeline '%s'", config.diarization_model)
    try:
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained(
            config.diarization_model,
            use_auth_token=config.hf_token,
        )
        pipeline.to(torch.device(config.device))
    except Exception as e:
        raise DiarizationError(f"Failed to load diarization pipeline: {e}")

    logger.info("Running diarization on %s ...", audio_path)
    try:
        diarization = pipeline(str(audio_path))
    except Exception as e:
        raise DiarizationError(f"Diarization failed: {e}")

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start": turn.start,
            "end": turn.end,
        })
    logger.info("Diarization produced %d segments", len(segments))
    return segments


# ---------------------------------------------------------------------------
# Step 5 – Align & merge
# ---------------------------------------------------------------------------

def align(whisper_result: dict, diarization_segments: list[dict]) -> list[Segment]:
    whisper_segments = whisper_result["segments"]
    if not diarization_segments:
        logger.warning("No diarization segments – falling back to single speaker")
        return [
            Segment(speaker="Speaker 1", start=s["start"], end=s["end"], text=s["text"].strip())
            for s in whisper_segments
        ]

    segments: list[Segment] = []
    for ws in whisper_segments:
        w_start = ws["start"]
        w_end = ws["end"]
        w_text = ws["text"].strip()
        if not w_text:
            continue

        overlaps = []
        for ds in diarization_segments:
            s = max(w_start, ds["start"])
            e = min(w_end, ds["end"])
            overlap = max(0.0, e - s)
            if overlap > 0:
                overlaps.append((overlap, ds["speaker"]))

        if overlaps:
            overlaps.sort(key=lambda x: x[0], reverse=True)
            speaker = overlaps[0][1]
        else:
            speaker = "Speaker 1"

        segments.append(Segment(speaker=speaker, start=w_start, end=w_end, text=w_text))

    return segments


# ---------------------------------------------------------------------------
# Run full pipeline for a single URL
# ---------------------------------------------------------------------------

def process_url(url: str) -> TranscriptionResult:
    with tempfile.TemporaryDirectory(dir=config.output_dir) as tmp:
        tmp_dir = Path(tmp)

        audio_raw = download_audio(url, tmp_dir)
        audio_wav = resample_audio(audio_raw, tmp_dir / "resampled.wav")

        whisper_out = transcribe(audio_wav)
        diarization_segments = diarize(audio_wav)
        aligned = align(whisper_out, diarization_segments)

        title = whisper_out.get("language", "unknown")
        duration = whisper_out.get("duration", 0.0)

        result = TranscriptionResult(
            url=url,
            title=title,
            duration=duration,
            segments=aligned,
            processed_at=datetime.utcnow(),
        )

    logger.info("Pipeline complete for %s (%d segments)", url, len(aligned))
    return result


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_batch(urls: list[str]) -> list[TranscriptionResult]:
    results: list[TranscriptionResult] = []
    for i, url in enumerate(urls, 1):
        logger.info("Processing [%d/%d]: %s", i, len(urls), url)
        try:
            result = process_url(url)
            results.append(result)
        except Exception as e:
            logger.error("Failed to process %s: %s", url, e)
    return results
