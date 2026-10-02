"""Reconcile source candidates against valid and rejected FHIR resources."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .alerts import AlertThresholds
from .models import (
    FHIR_SPEC_VERSION,
    FHIR_VERSION,
    ENCOUNTER_MAPPING_VERSION,
    ENCOUNTER_SOURCE_ASSUMPTION,
    PATIENT_MAPPING_VERSION,
    TERMINOLOGY_MAPPING_VERSION,
    RejectedRecord,
    RunContext,
)


def build_run_summary(
    *,
    context: RunContext,
    source_counts: Mapping[str, int],
    resources: Sequence[Mapping[str, Any]],
    rejected: Sequence[RejectedRecord],
    lineage_count: int,
    stage_durations_ms: Mapping[str, float],
    official_validation: Mapping[str, Any],
    alert_thresholds: AlertThresholds,
) -> dict[str, Any]:
    generated = Counter(str(resource["resourceType"]) for resource in resources)
    rejected_counts = Counter(record.resource_type for record in rejected)
    expected = {
        "Patient": int(source_counts.get("patient", 0)),
        "Encounter": int(source_counts.get("patient_visit", 0)),
    }
    reconciliation = {
        resource_type: {
            "expected": count,
            "generated": generated[resource_type],
            "rejected": rejected_counts[resource_type],
            "accounted_for": count
            == generated[resource_type] + rejected_counts[resource_type],
        }
        for resource_type, count in expected.items()
    }
    if not all(item["accounted_for"] for item in reconciliation.values()):
        raise RuntimeError("FHIR reconciliation failed: one or more records disappeared.")

    error_counts = Counter(record.error_code for record in rejected)
    candidates = sum(expected.values())
    success = len(resources)
    rejection_rate = len(rejected) / candidates if candidates else 0.0
    alerts: list[str] = []
    if generated["Patient"] < alert_thresholds.minimum_patients:
        alerts.append("PATIENT_COUNT_BELOW_MINIMUM")
    if generated["Encounter"] < alert_thresholds.minimum_encounters:
        alerts.append("ENCOUNTER_COUNT_BELOW_MINIMUM")
    if rejection_rate > alert_thresholds.max_rejection_rate:
        alerts.append("REJECTION_RATE_EXCEEDED")
    total_duration_ms = sum(float(value) for value in stage_durations_ms.values())
    if (
        alert_thresholds.max_duration_ms is not None
        and total_duration_ms > alert_thresholds.max_duration_ms
    ):
        alerts.append("RUN_DURATION_EXCEEDED")
    if official_validation.get("status") == "SKIPPED_UNAVAILABLE":
        alerts.append("OFFICIAL_FHIR_VALIDATION_UNAVAILABLE")
    status = (
        "COMPLETED_WITH_ERRORS"
        if rejected
        else "COMPLETED_WITH_ALERTS"
        if alerts
        else "COMPLETED"
    )
    return {
        "run_id": context.run_id,
        "implementation": context.implementation,
        "started_at": context.started_at,
        "status": status,
        "fhir_version": FHIR_VERSION,
        "fhir_spec_version": FHIR_SPEC_VERSION,
        "implementation_guide": {
            "poc_decision": "NOT_REQUIRED_BASE_R4",
            "selected_packages": list(
                official_validation.get("implementation_guides") or []
            ),
            "production_gate": (
                "Select the client/jurisdiction IG and profiles, or formally "
                "approve base R4 as the production contract."
            ),
        },
        "validation_scope": "base-r4-generated-patient-encounter-subset",
        "validation": {
            "lightweight_internal": "PASSED",
            "official_r4": dict(official_validation),
        },
        "mapping_assumptions": {
            "patient_visit": ENCOUNTER_SOURCE_ASSUMPTION,
        },
        "mapping_versions": {
            "Patient": PATIENT_MAPPING_VERSION,
            "Encounter": ENCOUNTER_MAPPING_VERSION,
            "terminology": TERMINOLOGY_MAPPING_VERSION,
        },
        "source_counts": dict(source_counts),
        "result": {
            "resource_candidates": candidates,
            "resources_generated": success,
            "resources_rejected": len(rejected),
            "success_rate": round(success / candidates, 6) if candidates else 0.0,
            "rejection_rate": round(rejection_rate, 6),
            "resource_counts": dict(sorted(generated.items())),
            "error_counts": dict(sorted(error_counts.items())),
            "lineage_records": lineage_count,
        },
        "reconciliation": reconciliation,
        "stage_durations_ms": {
            key: round(float(value), 3) for key, value in stage_durations_ms.items()
        },
        "alerts": alerts,
        "alert_thresholds": {
            "max_rejection_rate": alert_thresholds.max_rejection_rate,
            "max_duration_ms": alert_thresholds.max_duration_ms,
            "minimum_patients": alert_thresholds.minimum_patients,
            "minimum_encounters": alert_thresholds.minimum_encounters,
        },
    }
