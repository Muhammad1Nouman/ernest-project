"""CLI entry point for the Google ADK-powered agentic ETL pipeline."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROJECT_DIR.parent

if __package__:
    from .main import setup_logging
    from .agentic_etl.pipeline import run_agentic_etl
else:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from project.main import setup_logging
    from project.agentic_etl.pipeline import run_agentic_etl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=REPOSITORY_ROOT / "sqltojson.db")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "patient_output_agentic.json",
    )
    parser.add_argument(
        "--log", type=Path, default=PROJECT_DIR / "agentic_etl" / "log.txt"
    )
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log)
    logger = logging.getLogger("Agentic_ETL")
    logger.info("Starting Google ADK agentic ETL with model %s", args.model)

    try:
        count = asyncio.run(
            run_agentic_etl(
                args.db,
                args.output,
                batch_size=args.batch_size,
                concurrency=args.concurrency,
                model_name=args.model,
                max_attempts=args.max_attempts,
                request_timeout_seconds=args.timeout,
            )
        )
    except Exception:
        logger.exception("Agentic ETL failed")
        return 1

    logger.info("Agentic ETL completed with %d records", count)
    print(f"Agentic ETL complete: exported {count} records to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
