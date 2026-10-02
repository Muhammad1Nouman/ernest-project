"""Shared deterministic FHIR mapping controls for both implementations."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .encounter_mapper import map_encounter
from .patient_mapper import map_patient
from ..observability.errors import RecordProcessingError
from ..observability.models import (
    ENCOUNTER_MAPPING_VERSION,
    PATIENT_MAPPING_VERSION,
    LineageRecord,
    RejectedRecord,
    RunContext,
    utc_timestamp,
)
from ..validation.fhir_validator import validate_resource


class FHIRRunAccumulator:
    """Collect valid resources and account for every rejected candidate."""

    def __init__(self, context: RunContext) -> None:
        self.context = context
        self.resources: list[dict[str, Any]] = []
        self.rejected: list[RejectedRecord] = []
        self.lineage: list[LineageRecord] = []
        self.expected = Counter()
        self.mapping_seconds = 0.0
        self.validation_seconds = 0.0
        self._resource_keys: set[tuple[str, str]] = set()

    def register_source_payload(self, raw_payload: Mapping[str, Any]) -> None:
        self.expected["Patient"] += 1
        self.expected["Encounter"] += len(raw_payload.get("visits") or [])

    def _reject(
        self,
        *,
        source_table: str,
        source_pk: Any,
        resource_type: str,
        resource_id: str | None,
        error: RecordProcessingError,
        mapping_version: str,
    ) -> None:
        self.rejected.append(
            RejectedRecord(
                run_id=self.context.run_id,
                source_table=source_table,
                source_pk=str(source_pk) if source_pk is not None else "<missing>",
                resource_type=resource_type,
                resource_id=resource_id,
                stage=error.stage,
                error_code=error.code,
                error_message=str(error),
                failed_field=error.field,
                retryable=error.retryable,
                mapping_version=mapping_version,
                processed_at=utc_timestamp(),
            )
        )

    def reject_patient_tree(
        self, raw_payload: Mapping[str, Any], error: RecordProcessingError
    ) -> None:
        patient = raw_payload.get("patient") or {}
        patient_pk = patient.get("patient_id")
        resource_id = str(patient_pk) if patient_pk is not None else None
        self._reject(
            source_table="patient",
            source_pk=patient_pk,
            resource_type="Patient",
            resource_id=resource_id,
            error=error,
            mapping_version=PATIENT_MAPPING_VERSION,
        )
        for visit in raw_payload.get("visits") or []:
            dependency_error = RecordProcessingError(
                "REL_PATIENT_REFERENCE_NOT_FOUND",
                "Encounter cannot be emitted because its Patient resource was rejected.",
                stage="REFERENCE_VALIDATION",
                field="subject.reference",
            )
            visit_pk = visit.get("patient_visit_id")
            self._reject(
                source_table="patient_visit",
                source_pk=visit_pk,
                resource_type="Encounter",
                resource_id=str(visit_pk) if visit_pk is not None else None,
                error=dependency_error,
                mapping_version=ENCOUNTER_MAPPING_VERSION,
            )

    def _accept(
        self,
        resource: dict[str, Any],
        *,
        source_table: str,
        source_pk: Any,
        mapping_version: str,
    ) -> None:
        key = (str(resource["resourceType"]), str(resource["id"]))
        if key in self._resource_keys:
            raise RecordProcessingError(
                "FHIR_DUPLICATE_RESOURCE_ID",
                "A duplicate FHIR resource identity was generated.",
                stage="FHIR_VALIDATION",
                field="id",
            )
        self._resource_keys.add(key)
        self.resources.append(resource)
        self.lineage.append(
            LineageRecord(
                run_id=self.context.run_id,
                source_table=source_table,
                source_pk=str(source_pk),
                resource_type=key[0],
                resource_id=key[1],
                mapping_version=mapping_version,
                processed_at=utc_timestamp(),
            )
            )

    def reject_visit(
        self, raw_visit: Mapping[str, Any], error: RecordProcessingError
    ) -> None:
        visit_pk = raw_visit.get("patient_visit_id")
        self._reject(
            source_table="patient_visit",
            source_pk=visit_pk,
            resource_type="Encounter",
            resource_id=str(visit_pk) if visit_pk is not None else None,
            error=error,
            mapping_version=ENCOUNTER_MAPPING_VERSION,
        )

    def process_patient(
        self,
        normalized: Mapping[str, Any],
        raw_payload: Mapping[str, Any],
    ) -> str | None:
        patient = normalized["patient"]
        patient_pk = patient.get("patient_id")
        patient_id = str(patient_pk) if patient_pk is not None else None
        try:
            started = time.perf_counter()
            patient_resource = map_patient(normalized)
            self.mapping_seconds += time.perf_counter() - started
            started = time.perf_counter()
            validate_resource(patient_resource)
            self.validation_seconds += time.perf_counter() - started
            self._accept(
                patient_resource,
                source_table="patient",
                source_pk=patient_pk,
                mapping_version=PATIENT_MAPPING_VERSION,
            )
        except RecordProcessingError as error:
            self.reject_patient_tree(raw_payload, error)
            return None

        return str(patient_resource["id"])

    def process_visit(
        self,
        visit: Mapping[str, Any],
        raw_visit: Mapping[str, Any],
        *,
        patient_id: str,
    ) -> None:
        visit_pk = visit.get("patient_visit_id")
        visit_id = str(visit_pk) if visit_pk is not None else None
        try:
            started = time.perf_counter()
            encounter = map_encounter(visit, patient_id)
            self.mapping_seconds += time.perf_counter() - started
            started = time.perf_counter()
            validate_resource(encounter)
            self.validation_seconds += time.perf_counter() - started
            self._accept(
                encounter,
                source_table="patient_visit",
                source_pk=visit_pk,
                mapping_version=ENCOUNTER_MAPPING_VERSION,
            )
        except RecordProcessingError as error:
            self._reject(
                source_table="patient_visit",
                source_pk=visit_pk,
                resource_type="Encounter",
                resource_id=visit_id,
                error=error,
                mapping_version=ENCOUNTER_MAPPING_VERSION,
            )

    def process_normalized(
        self,
        normalized: Mapping[str, Any],
        raw_payload: Mapping[str, Any],
    ) -> None:
        """Compatibility helper for already-normalized complete aggregates."""
        patient_id = self.process_patient(normalized, raw_payload)
        if patient_id is None:
            return
        raw_visits = list(raw_payload.get("visits") or [])
        for index, visit in enumerate(normalized.get("visits") or []):
            raw_visit = raw_visits[index] if index < len(raw_visits) else visit
            self.process_visit(visit, raw_visit, patient_id=patient_id)
