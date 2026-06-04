from __future__ import annotations

import logging
from datetime import datetime

from supabase import create_client, Client
from config import config
from models import TranscriptionResult, Segment

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.supabase_url, config.supabase_key)
    return _client


def save_result(result: TranscriptionResult) -> int | None:
    try:
        client = get_client()
        payload = {
            "url": result.url,
            "title": result.title,
            "duration": result.duration,
            "segments": [
                {"speaker": s.speaker, "start": s.start, "end": s.end, "text": s.text}
                for s in result.segments
            ],
            "processed_at": result.processed_at.isoformat(),
        }
        resp = client.table("transcriptions").insert(payload).execute()
        if resp.data:
            row_id = resp.data[0].get("id")
            logger.info("Saved transcription id=%s for url=%s", row_id, result.url)
            return row_id
        logger.warning("No data returned for url=%s", result.url)
        return None
    except Exception as e:
        logger.error("Failed to save result for %s: %s", result.url, e)
        return None


def get_all() -> list[TranscriptionResult]:
    try:
        client = get_client()
        resp = (
            client.table("transcriptions")
            .select("url, title, duration, segments, processed_at")
            .order("processed_at", desc=True)
            .execute()
        )
        results = []
        for row in resp.data:
            segments = [
                Segment(speaker=s["speaker"], start=s["start"], end=s["end"], text=s["text"])
                for s in row["segments"]
            ]
            results.append(TranscriptionResult(
                url=row["url"],
                title=row.get("title") or "",
                duration=row.get("duration") or 0.0,
                segments=segments,
                processed_at=datetime.fromisoformat(row["processed_at"]),
            ))
        return results
    except Exception as e:
        logger.error("Failed to fetch transcriptions: %s", e)
        return []
