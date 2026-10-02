"""Command-line entry point for the SQL-to-JSON ETL pipeline."""

from __future__ import annotations
import argparse
import logging
import os
import stat
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROJECT_DIR.parent

if __package__:
    from .extract.extractor import SQLiteExtractor
    from .fhir.finalize import finalize_run
    from .fhir.processor import FHIRRunAccumulator
    from .observability.errors import RecordProcessingError
    from .observability.alerts import AlertThresholds
    from .observability.logging import SafeJSONFormatter, set_log_context
    from .observability.models import PipelineResult, RunContext
    from .observability.retry import RetryPolicy
    from .transform.normalizer import SourceNormalizer
    from .validation.official_validator import (
        OfficialFHIRValidator,
        OfficialValidatorConfig,
    )
else:  # Support direct execution with: python project/main.py
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from project.extract.extractor import SQLiteExtractor
    from project.fhir.finalize import finalize_run
    from project.fhir.processor import FHIRRunAccumulator
    from project.observability.errors import RecordProcessingError
    from project.observability.alerts import AlertThresholds
    from project.observability.logging import SafeJSONFormatter, set_log_context
    from project.observability.models import PipelineResult, RunContext
    from project.observability.retry import RetryPolicy
    from project.transform.normalizer import SourceNormalizer
    from project.validation.official_validator import (
        OfficialFHIRValidator,
        OfficialValidatorConfig,
    )

DEFAULT_DB_PATH = REPOSITORY_ROOT / "sqltojson.db"
DEFAULT_OUTPUT_PATH = REPOSITORY_ROOT / "patient_output.json"
DEFAULT_LOG_PATH = PROJECT_DIR / "log.txt"

def setup_logging(log_path: str | Path = DEFAULT_LOG_PATH) -> None:
    """Sets up runtime logging to both log file and console stderr."""
    resolved_log_path = Path(log_path).resolve()
    resolved_log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = SafeJSONFormatter()

    # File Handler
    file_handler = logging.FileHandler(resolved_log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Console Handler (Stream to stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for existing_handler in root_logger.handlers[:]:
        root_logger.removeHandler(existing_handler)
        existing_handler.close()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    try:
        os.chmod(resolved_log_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def run_pipeline(
    db_path: str | Path = DEFAULT_DB_PATH,
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    log_path: str | Path = DEFAULT_LOG_PATH,
    *,
    run_id: str | None = None,
    retry_policy: RetryPolicy | None = None,
    official_validator_config: OfficialValidatorConfig | None = None,
    official_validator: OfficialFHIRValidator | None = None,
    alert_thresholds: AlertThresholds | None = None,
) -> PipelineResult:
    """Run deterministic source normalization and FHIR R4 mapping."""
    setup_logging(log_path)
    logger = logging.getLogger("ETL_Pipeline")
    context = RunContext.create("deterministic", run_id)
    set_log_context(context.run_id, context.implementation)
    logger.info(
        "Starting deterministic FHIR R4 ETL",
        extra={
            "event": "run_started",
            "run_id": context.run_id,
            "implementation": context.implementation,
            "stage": "START",
        },
    )

    active_retry_policy = retry_policy or RetryPolicy()
    extractor = SQLiteExtractor(db_path, retry_policy=active_retry_policy)
    normalizer = SourceNormalizer()
    accumulator = FHIRRunAccumulator(context)

    extraction_started = time.perf_counter()
    payloads = list(extractor.iter_patients())
    extraction_ms = (time.perf_counter() - extraction_started) * 1000
    source_counts = {
        "patient": len(payloads),
        "patient_address": sum(1 for payload in payloads if payload.get("address")),
        "patient_visit": sum(len(payload.get("visits") or []) for payload in payloads),
    }
    logger.info(
        "Source extraction completed",
        extra={
            "event": "stage_completed",
            "run_id": context.run_id,
            "implementation": context.implementation,
            "stage": "EXTRACT",
            "count": sum(source_counts.values()),
            "duration_ms": round(extraction_ms, 3),
        },
    )

    normalization_started = time.perf_counter()
    for payload in payloads:
        accumulator.register_source_payload(payload)
        try:
            normalized = normalizer.normalize_patient(payload)
        except RecordProcessingError as error:
            accumulator.reject_patient_tree(payload, error)
            continue
        patient_id = accumulator.process_patient(normalized, payload)
        if patient_id is None:
            continue
        source_patient_id = payload["patient"]["patient_id"]
        for raw_visit in payload.get("visits") or []:
            try:
                visit = normalizer.normalize_visit(
                    raw_visit, patient_id=source_patient_id
                )
            except RecordProcessingError as error:
                accumulator.reject_visit(raw_visit, error)
                continue
            accumulator.process_visit(
                visit, raw_visit, patient_id=patient_id
            )
    normalization_ms = (time.perf_counter() - normalization_started) * 1000

    return finalize_run(
        context=context,
        accumulator=accumulator,
        source_counts=source_counts,
        output_path=output_path,
        stage_durations_ms={
            "extraction": extraction_ms,
            "normalization": normalization_ms,
        },
        retry_policy=active_retry_policy,
        official_validator_config=official_validator_config,
        official_validator=official_validator,
        alert_thresholds=alert_thresholds,
    )


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
    parser.add_argument("--run-id", help="Optional stable identifier for this run")
    parser.add_argument(
        "--official-validation",
        choices=("off", "if-available", "required"),
        help="HL7 Validator policy (default: FHIR_VALIDATOR_MODE or if-available)",
    )
    parser.add_argument(
        "--fhir-validator-jar",
        type=Path,
        help="Path to the official HL7 validator_cli.jar",
    )
    parser.add_argument(
        "--fhir-validator-timeout",
        type=float,
        default=180.0,
        help="Seconds allowed for each official validator attempt",
    )
    parser.add_argument(
        "--implementation-guide",
        action="append",
        default=[],
        help="FHIR package/canonical passed to the validator; repeat as needed",
    )
    parser.add_argument("--technical-attempts", type=int, default=3)
    parser.add_argument("--technical-initial-delay", type=float, default=0.25)
    parser.add_argument("--technical-max-delay", type=float, default=2.0)
    parser.add_argument("--max-rejection-rate", type=float, default=0.02)
    parser.add_argument("--max-duration-ms", type=float, default=60_000.0)
    parser.add_argument("--minimum-patients", type=int, default=1)
    parser.add_argument("--minimum-encounters", type=int, default=1)
    parser.add_argument(
        "--fail-on-rejections",
        action="store_true",
        help="Return exit code 2 after safely publishing quarantined results",
    )
    parser.add_argument(
        "--fail-on-alerts",
        action="store_true",
        help="Return exit code 3 when configured alert thresholds are breached",
    )
    return parser

def main(argv: list[str] | None = None) -> int:
    """Main CLI execution handler."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        retry_policy = RetryPolicy(
            max_attempts=args.technical_attempts,
            initial_delay_seconds=args.technical_initial_delay,
            max_delay_seconds=args.technical_max_delay,
        )
        official_validator_config = OfficialValidatorConfig.from_environment(
            mode=args.official_validation,
            jar_path=args.fhir_validator_jar,
            timeout_seconds=args.fhir_validator_timeout,
            implementation_guides=args.implementation_guide,
        )
        alert_thresholds = AlertThresholds(
            max_rejection_rate=args.max_rejection_rate,
            max_duration_ms=args.max_duration_ms,
            minimum_patients=args.minimum_patients,
            minimum_encounters=args.minimum_encounters,
        )
        result = run_pipeline(
            args.db,
            args.output,
            args.log,
            run_id=args.run_id,
            retry_policy=retry_policy,
            official_validator_config=official_validator_config,
            alert_thresholds=alert_thresholds,
        )
        json_string = args.output.resolve().read_text(encoding="utf-8")
    except Exception as error:
        logger = logging.getLogger("ETL_Pipeline")
        logger.exception("Pipeline execution failed: %s", type(error).__name__)
        return 1

    # The assignment requires the generated JSON string on stdout. Runtime
    # status remains in log.txt and on stderr through the logging handler.
    print(json_string, end="" if json_string.endswith("\n") else "\n")
    if args.fail_on_rejections and result.resources_rejected:
        return 2
    if args.fail_on_alerts and result.alert_count:
        return 3
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
