"""Command-line entry point for the SQL-to-JSON ETL pipeline."""

from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROJECT_DIR.parent

if __package__:
    from .extract.extractor import SQLiteExtractor
    from .load.loader import JSONLoader
    from .transform.transformer import DataTransformer
else:  # Support direct execution with: python project/main.py
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from project.extract.extractor import SQLiteExtractor
    from project.load.loader import JSONLoader
    from project.transform.transformer import DataTransformer

DEFAULT_DB_PATH = REPOSITORY_ROOT / "sqltojson.db"
DEFAULT_OUTPUT_PATH = REPOSITORY_ROOT / "patient_output.json"
DEFAULT_LOG_PATH = PROJECT_DIR / "log.txt"

def setup_logging(log_path: str | Path = DEFAULT_LOG_PATH) -> None:
    """Sets up runtime logging to both log file and console stderr."""
    resolved_log_path = Path(log_path).resolve()
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # File Handler
    file_handler = logging.FileHandler(resolved_log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Console Handler (Stream to stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def run_pipeline(
    db_path: str | Path = DEFAULT_DB_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    log_path: str | Path = DEFAULT_LOG_PATH,
) -> int:
    """Run the streaming ETL pipeline and return the exported record count."""
    setup_logging(log_path)
    logger = logging.getLogger("ETL_Pipeline")
    logger.info("Starting deterministic ETL pipeline")

    extractor = SQLiteExtractor(db_path)
    transformer = DataTransformer()
    loader = JSONLoader(output_path)

    # Clean streaming pipeline through generator chain
    transformed_records = transformer.transform_iter(extractor.iter_patients())
    count = loader.load(transformed_records)
    
    logger.info("ETL pipeline completed successfully with %d records", count)
    return count


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line argument interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to source SQLite database file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for target output JSON file",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Path for application runtime log file",
    )
    return parser

def main(argv: list[str] | None = None) -> int:
    """Main CLI execution handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        count = run_pipeline(args.db, args.output, args.log)
        json_string = args.output.resolve().read_text(encoding="utf-8")
    except Exception as error:
        logger = logging.getLogger("ETL_Pipeline")
        logger.exception("Pipeline execution failed: %s", error)
        return 1

    # The assignment requires the generated JSON string on stdout. Runtime
    # status remains in log.txt and on stderr through the logging handler.
    print(json_string, end="" if json_string.endswith("\n") else "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
