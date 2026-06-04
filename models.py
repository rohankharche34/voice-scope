from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Segment:
    speaker: str
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    url: str
    title: str
    duration: float
    segments: list[Segment]
    processed_at: datetime

    def to_json(self) -> str:
        return json.dumps({
            "url": self.url,
            "title": self.title,
            "duration": self.duration,
            "segments": [
                {
                    "speaker": s.speaker,
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text,
                }
                for s in self.segments
            ],
            "processed_at": self.processed_at.isoformat(),
        }, indent=2, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "duration": self.duration,
            "segments": [
                {
                    "speaker": s.speaker,
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text,
                }
                for s in self.segments
            ],
            "processed_at": self.processed_at,
        }
