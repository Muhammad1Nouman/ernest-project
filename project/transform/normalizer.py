"""Deterministic source cleanup performed before FHIR semantic mapping."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from ..observability.errors import RecordProcessingError
from .schemas import (
    SchemaValidationError,
    validate_patient_and_address,
    validate_visit,
)


def clean_value(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.upper() in {"NULL", "NONE", "N/A"}:
            return None
        return cleaned
    return value


def normalize_date(value: Any, field: str) -> str:
    cleaned = clean_value(value)
    if cleaned is None:
        raise RecordProcessingError(
            "SRC_REQUIRED_FIELD_MISSING",
            f"Required source field '{field}' is missing.",
            stage="SOURCE_VALIDATION",
            field=field,
        )
    candidate = str(cleaned).replace(" ", "T", 1)
    try:
        if len(candidate) == 10:
            return date.fromisoformat(candidate).isoformat()
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date().isoformat()
    except ValueError as error:
        raise RecordProcessingError(
            "SRC_INVALID_DATE",
            f"Source field '{field}' is not a valid date.",
            stage="NORMALIZATION",
            field=field,
        ) from error


def normalize_date_time(value: Any, field: str) -> str:
    cleaned = clean_value(value)
    if cleaned is None:
        raise RecordProcessingError(
            "SRC_REQUIRED_FIELD_MISSING",
            f"Required source field '{field}' is missing.",
            stage="SOURCE_VALIDATION",
            field=field,
        )
    candidate = str(cleaned).replace(" ", "T", 1)
    try:
        if len(candidate) == 10:
            return date.fromisoformat(candidate).isoformat()
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as error:
        raise RecordProcessingError(
            "SRC_INVALID_DATE",
            f"Source field '{field}' is not a valid date/time.",
            stage="NORMALIZATION",
            field=field,
        ) from error
    # The sample source has no timezone. FHIR dateTime requires an offset when
    # time is present, so retain only the date precision instead of inventing one.
    if parsed.tzinfo is None:
        return parsed.date().isoformat()
    return parsed.isoformat(timespec="seconds")


class SourceNormalizer:
    """Normalize validated relational aggregates without applying FHIR semantics."""

    def normalize_patient(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            validate_patient_and_address(payload)
        except SchemaValidationError as error:
            raise RecordProcessingError(
                "SRC_VALIDATION_FAILED",
                "Source record failed required-field, datatype, or relationship validation.",
                stage="SOURCE_VALIDATION",
            ) from error

        patient = payload["patient"]
        active = patient.get("active")
        if isinstance(active, bool):
            normalized_active = active
        elif isinstance(active, int) and active in (0, 1):
            normalized_active = bool(active)
        else:
            raise RecordProcessingError(
                "SRC_INVALID_DATATYPE",
                "Source active flag must be 0, 1, or a boolean.",
                stage="SOURCE_VALIDATION",
                field="active",
            )

        normalized_patient = {
            "patient_id": patient["patient_id"],
            "mrn": clean_value(patient.get("mrn")),
            "first_name": clean_value(patient.get("first_name")),
            "middle_name": clean_value(patient.get("middle_name")),
            "last_name": clean_value(patient.get("last_name")),
            "suffix": clean_value(patient.get("suffix")),
            "birth_date": normalize_date(patient.get("dob"), "dob"),
            "gender_source": clean_value(patient.get("sex")),
            "active": normalized_active,
            "home_phone": clean_value(patient.get("home_phone")),
            "mobile_phone": clean_value(patient.get("mobile_phone")),
            "email": clean_value(patient.get("email")),
        }

        address = payload.get("address")
        normalized_address = None
        if isinstance(address, Mapping):
            if address.get("patient_id") != patient["patient_id"] or address.get(
                "address_id"
            ) != patient.get("patient_address_id"):
                raise RecordProcessingError(
                    "REL_ADDRESS_PATIENT_MISMATCH",
                    "Patient and address relationship identifiers do not agree.",
                    stage="SOURCE_VALIDATION",
                    field="patient_address_id",
                )
            lines = [clean_value(address.get("address_line1"))]
            line_2 = clean_value(address.get("address_line2"))
            if line_2:
                lines.append(line_2)
            normalized_address = {
                "address_id": address.get("address_id"),
                "lines": [line for line in lines if line],
                "city": clean_value(address.get("city")),
                "state": clean_value(address.get("state")),
                "postal_code": clean_value(address.get("zip_code")),
            }

        return {
            "patient": normalized_patient,
            "address": normalized_address,
            "visits": [],
        }

    def normalize_visit(
        self, visit: Mapping[str, Any], *, patient_id: int
    ) -> dict[str, Any]:
        try:
            validate_visit(visit, patient_id)
        except SchemaValidationError as error:
            raise RecordProcessingError(
                "SRC_VALIDATION_FAILED",
                "Visit failed required-field, datatype, or relationship validation.",
                stage="SOURCE_VALIDATION",
            ) from error
        return {
            "patient_visit_id": visit.get("patient_visit_id"),
            "patient_id": visit.get("patient_id"),
            "start": normalize_date_time(visit.get("visit_date"), "visit_date"),
        }

    def normalize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Normalize a complete payload for compatibility and simple callers."""
        normalized = self.normalize_patient(payload)
        patient_id = payload["patient"]["patient_id"]
        normalized["visits"] = [
            self.normalize_visit(visit, patient_id=patient_id)
            for visit in payload.get("visits") or []
        ]
        return normalized
