from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from database import save_result
from pipeline import process_batch
from config import config

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.output_dir / "voicescope.log"),
        ],
    )


def load_urls(source: str) -> list[str]:
    p = Path(source)
    if p.exists():
        return [line.strip() for line in p.read_text().splitlines() if line.strip()]
    return [source]


def main() -> None:
    setup_logging()
    logger.info("VoiceScope starting")

    parser = argparse.ArgumentParser(description="VoiceScope – Speech Processing Pipeline")
    parser.add_argument("urls", nargs="*", help="YouTube URL(s) or path(s) to URL file(s)")
    parser.add_argument("-f", "--file", help="Path to a file containing URLs (one per line)")
    parser.add_argument("-o", "--output", type=Path, help="Output JSON file path")
    parser.add_argument(
        "--save-db", action="store_true", default=True,
        help="Save results to Supabase (default: True)",
    )
    parser.add_argument(
        "--no-save-db", action="store_false", dest="save_db",
        help="Skip saving to Supabase",
    )

    args = parser.parse_args()

    sources: list[str] = []
    if args.file:
        sources.extend(load_urls(args.file))
    for u in args.urls:
        sources.extend(load_urls(u))

    if not sources:
        parser.print_help()
        sys.exit(1)

    results = process_batch(sources)

    if args.output:
        combined = [r.to_dict() for r in results]
        args.output.write_text(
            json.dumps(combined, indent=2, ensure_ascii=False, default=str)
        )
        logger.info("Wrote combined output to %s", args.output)

    for result in results:
        if args.output is None:
            print(result.to_json())
            print("-" * 60)
        if args.save_db:
            save_result(result)

    logger.info("VoiceScope finished – %d/%d succeeded", len(results), len(sources))


if __name__ == "__main__":
    main()
