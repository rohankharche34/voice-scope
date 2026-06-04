from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    supabase_url: str = field(
        default_factory=lambda: os.getenv("SUPABASE_URL", "")
    )
    supabase_key: str = field(
        default_factory=lambda: os.getenv("SUPABASE_KEY", "")
    )
    hf_token: str = field(
        default_factory=lambda: os.getenv("HF_TOKEN", "")
    )
    whisper_model: str = field(
        default_factory=lambda: os.getenv("WHISPER_MODEL", "base")
    )
    diarization_model: str = field(
        default_factory=lambda: os.getenv(
            "DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
        )
    )
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "./output"))
    )
    sample_rate: int = field(
        default_factory=lambda: int(os.getenv("SAMPLE_RATE", "16000"))
    )
    device: str = field(
        default_factory=lambda: os.getenv("DEVICE", "cpu")
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    whisper_device: str = field(init=False)

    def __post_init__(self) -> None:
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.whisper_device = "cuda" if self.device == "cuda" else "cpu"


config = Config()
