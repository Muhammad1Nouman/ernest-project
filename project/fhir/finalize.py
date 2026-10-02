"""Shared reconciliation, Bundle construction, and publication."""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from .bundle import build_collection_bundle
from .processor import FHIRRunAccumulator
from ..load.loader import FHIRArtifactLoader
from ..observability.alerts import AlertThresholds
from ..observability.models import PipelineResult, RunContext
from ..observability.reconciliation import build_run_summary
from ..observability.retry import RetryPolicy
from ..validation.fhir_validator import validate_collection_bundle
from ..validation.official_validator import (
    OfficialFHIRValidator,
    OfficialValidatorConfig,
)
from ..validation.reference_validator import validate_references


def finalize_run(
    *,
    context: RunContext,
    accumulator: FHIRRunAccumulator,
    source_counts: Mapping[str, int],
    output_path: str | Path,
    stage_durations_ms: dict[str, float],
    retry_policy: RetryPolicy | None = None,
    official_validator_config: OfficialValidatorConfig | None = None,
    official_validator: OfficialFHIRValidator | None = None,
    alert_thresholds: AlertThresholds | None = None,
) -> PipelineResult:
    logger = logging.getLogger("FHIR_ETL")
    started = time.perf_counter()
    validate_references(accumulator.resources)
    bundle = build_collection_bundle(
        accumulator.resources,
        run_id=context.run_id,
        timestamp=context.started_at,
    )
    validate_collection_bundle(bundle)
    stage_durations_ms["validation"] = (
        accumulator.validation_seconds + time.perf_counter() - started
    ) * 1000
    stage_durations_ms["mapping"] = accumulator.mapping_seconds * 1000
    active_retry_policy = retry_policy or RetryPolicy()
    active_official_validator = official_validator or OfficialFHIRValidator(
        official_validator_config or OfficialValidatorConfig.from_environment(),
        retry_policy=active_retry_policy,
    )
    official_result = active_official_validator.validate(bundle)
    stage_durations_ms["official_validation"] = official_result.duration_ms

    summary = build_run_summary(
        context=context,
        source_counts=source_counts,
        resources=accumulator.resources,
        rejected=accumulator.rejected,
        lineage_count=len(accumulator.lineage),
        stage_durations_ms=stage_durations_ms,
        official_validation=official_result.to_dict(),
        alert_thresholds=alert_thresholds or AlertThresholds(),
    )
    loader = FHIRArtifactLoader(output_path, retry_policy=active_retry_policy)
    paths = loader.load_artifacts(
        bundle=bundle,
        rejected=(record.to_dict() for record in accumulator.rejected),
        lineage=(record.to_dict() for record in accumulator.lineage),
        summary=summary,
    )

    counts = Counter(resource["resourceType"] for resource in accumulator.resources)
    logger.info(
        "FHIR ETL run completed",
        extra={
            "event": "run_completed",
            "run_id": context.run_id,
            "implementation": context.implementation,
            "stage": "COMPLETE",
            "status": summary["status"],
            "count": len(accumulator.resources),
        },
    )
    for error_code, count in summary["result"]["error_counts"].items():
        logger.warning(
            "Records quarantined",
            extra={
                "event": "quarantine_summary",
                "run_id": context.run_id,
                "implementation": context.implementation,
                "stage": "QUARANTINE",
                "error_code": error_code,
                "count": count,
            },
        )
    for alert_code in summary["alerts"]:
        logger.warning(
            "Operational alert threshold breached",
            extra={
                "event": "operational_alert",
                "run_id": context.run_id,
                "implementation": context.implementation,
                "stage": "ALERT",
                "error_code": alert_code,
            },
        )
    return PipelineResult(
        run_id=context.run_id,
        status=str(summary["status"]),
        output_path=paths["output"],
        rejected_path=paths["rejected"],
        lineage_path=paths["lineage"],
        summary_path=paths["summary"],
        resources_generated=len(accumulator.resources),
        resources_rejected=len(accumulator.rejected),
        patient_resources=counts["Patient"],
        encounter_resources=counts["Encounter"],
        official_validation_status=official_result.status,
        alert_count=len(summary["alerts"]),
    )
