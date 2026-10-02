"""Map normalized visit rows to base FHIR R4 Encounter resources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .identifiers import ENCOUNTER_IDENTIFIER_SYSTEM, full_url, source_integer_id
from .terminology import ENCOUNTER_CLASS
from ..observability.errors import RecordProcessingError
from ..observability.models import (
    ENCOUNTER_MAPPING_VERSION,
    ENCOUNTER_SOURCE_ASSUMPTION,
)


def map_encounter(visit: Mapping[str, Any], patient_id: str) -> dict[str, Any]:
    encounter_id = source_integer_id(
        visit.get("patient_visit_id"), "patient_visit_id"
    )
    if str(visit.get("patient_id")) != patient_id:
        raise RecordProcessingError(
            "REL_ENCOUNTER_PATIENT_MISMATCH",
            "Encounter source patient identifier does not match its parent.",
            stage="SOURCE_VALIDATION",
            field="patient_id",
        )
    start = visit.get("start")
    if not isinstance(start, str) or not start:
        raise RecordProcessingError(
            "FHIR_INVALID_DATE",
            "Encounter period start is missing after normalization.",
            stage="FHIR_MAPPING",
            field="period.start",
        )
    return {
        "resourceType": "Encounter",
        "id": encounter_id,
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/Encounter"],
            "tag": [
                {
                    "system": "https://example.org/fhir/mapping-version",
                    "code": ENCOUNTER_MAPPING_VERSION,
                },
                {
                    "system": "https://example.org/fhir/source-assumption",
                    "code": "completed-ambulatory",
                    "display": ENCOUNTER_SOURCE_ASSUMPTION,
                },
            ],
        },
        "identifier": [
            {"system": ENCOUNTER_IDENTIFIER_SYSTEM, "value": encounter_id}
        ],
        "status": "finished",
        "class": dict(ENCOUNTER_CLASS),
        "subject": {"reference": full_url("Patient", patient_id)},
        "period": {"start": start},
    }
