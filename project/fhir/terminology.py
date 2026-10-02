"""Centralized FHIR R4 terminology mappings."""

from __future__ import annotations

from typing import Any

from ..observability.errors import RecordProcessingError

GENDER_MAP = {
    "M": "male",
    "MALE": "male",
    "F": "female",
    "FEMALE": "female",
    "OTHER": "other",
    "UNKNOWN": "unknown",
}

ENCOUNTER_CLASS = {
    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
    "code": "AMB",
    "display": "ambulatory",
}


def map_gender(value: Any) -> str:
    key = "" if value is None else str(value).strip().upper()
    mapped = GENDER_MAP.get(key)
    if mapped is None:
        raise RecordProcessingError(
            "TERM_GENDER_MAPPING_FAILED",
            "No FHIR R4 administrative-gender mapping exists for the source value.",
            stage="TERMINOLOGY_MAPPING",
            field="gender",
        )
    return mapped

