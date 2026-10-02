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
    from .observability.alerts import AlertThresholds
    from .observability.retry import RetryPolicy
    from .validation.official_validator import OfficialValidatorConfig
else:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from project.main import setup_logging
    from project.agentic_etl.pipeline import run_agentic_etl
    from project.observability.alerts import AlertThresholds
    from project.observability.retry import RetryPolicy
    from project.validation.official_validator import OfficialValidatorConfig


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
    parser.add_argument("--run-id")
    parser.add_argument(
        "--official-validation",
        choices=("off", "if-available", "required"),
        help="HL7 Validator policy (default: FHIR_VALIDATOR_MODE or if-available)",
    )
    parser.add_argument("--fhir-validator-jar", type=Path)
    parser.add_argument("--fhir-validator-timeout", type=float, default=180.0)
    parser.add_argument(
        "--implementation-guide", action="append", default=[]
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
    parser.add_argument("--fail-on-alerts", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.log)
    logger = logging.getLogger("Agentic_ETL")

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
        result = asyncio.run(
            run_agentic_etl(
                args.db,
                args.output,
                batch_size=args.batch_size,
                concurrency=args.concurrency,
                model_name=args.model,
                max_attempts=args.max_attempts,
                request_timeout_seconds=args.timeout,
                run_id=args.run_id,
                retry_policy=retry_policy,
                official_validator_config=official_validator_config,
                alert_thresholds=alert_thresholds,
            )
        )
    except Exception:
        logger.exception("Agentic ETL failed")
        return 1

    logger.info(
        "Agentic FHIR ETL completed",
        extra={
            "event": "cli_completed",
            "run_id": result.run_id,
            "implementation": "agentic",
            "stage": "COMPLETE",
            "status": result.status,
            "count": result.resources_generated,
        },
    )
    print(
        f"Agentic FHIR ETL {result.status}: exported "
        f"{result.resources_generated} resources to {result.output_path} "
        f"with {result.resources_rejected} rejected."
    )
    if args.fail_on_rejections and result.resources_rejected:
        return 2
    if args.fail_on_alerts and result.alert_count:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
