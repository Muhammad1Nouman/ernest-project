"""Run context, lineage, quarantine, and result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
import re


FHIR_VERSION = "R4"
FHIR_SPEC_VERSION = "4.0.1"
PATIENT_MAPPING_VERSION = "patient-r4-v1.0"
ENCOUNTER_MAPPING_VERSION = "encounter-r4-v1.0"
TERMINOLOGY_MAPPING_VERSION = "terminology-r4-v1.0"
ENCOUNTER_SOURCE_ASSUMPTION = (
    "patient_visit = completed ambulatory Encounter"
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"fhir-{now.strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    implementation: str
    started_at: str

    @classmethod
    def create(cls, implementation: str, run_id: str | None = None) -> "RunContext":
        resolved_run_id = run_id or new_run_id()
        if not re.fullmatch(r"[A-Za-z0-9\-.]{1,64}", resolved_run_id):
            raise ValueError(
                "run_id must be 1-64 characters using only letters, digits, '-', or '.'."
            )
        return cls(
            run_id=resolved_run_id,
            implementation=implementation,
            started_at=utc_timestamp(),
        )


@dataclass(frozen=True)
class LineageRecord:
    run_id: str
    source_table: str
    source_pk: str
    resource_type: str
    resource_id: str
    mapping_version: str
    processed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedRecord:
    run_id: str
    source_table: str
    source_pk: str
    resource_type: str
    resource_id: str | None
    stage: str
    error_code: str
    error_message: str
    failed_field: str | None
    retryable: bool
    mapping_version: str
    processed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    status: str
    output_path: Path
    rejected_path: Path
    lineage_path: Path
    summary_path: Path
    resources_generated: int
    resources_rejected: int
    patient_resources: int
    encounter_resources: int
    official_validation_status: str
    alert_count: int
