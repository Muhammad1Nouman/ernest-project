"""Deterministic FHIR R4 resource identity helpers."""

from __future__ import annotations

import re
import uuid
from typing import Any

from ..observability.errors import RecordProcessingError

FHIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
PATIENT_MRN_SYSTEM = "https://example.org/fhir/sid/mrn"
ENCOUNTER_IDENTIFIER_SYSTEM = "https://example.org/fhir/sid/encounter"


def source_integer_id(value: Any, field: str) -> str:
    if isinstance(value, bool):
        value = None
    text = "" if value is None else str(value).strip()
    try:
        if int(text) <= 0:
            raise ValueError
    except ValueError as error:
        raise RecordProcessingError(
            "SRC_INVALID_IDENTIFIER",
            f"Source field '{field}' must be a positive integer identifier.",
            stage="SOURCE_VALIDATION",
            field=field,
        ) from error
    if not FHIR_ID_PATTERN.fullmatch(text):
        raise RecordProcessingError(
            "FHIR_INVALID_ID",
            f"Source field '{field}' cannot form a FHIR id.",
            stage="FHIR_MAPPING",
            field=field,
        )
    return text


def full_url(resource_type: str, resource_id: str) -> str:
    logical = f"https://example.org/fhir/{resource_type}/{resource_id}"
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, logical)}"

