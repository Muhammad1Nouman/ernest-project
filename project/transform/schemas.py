"""Runtime validation for records crossing ETL stage boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class SchemaValidationError(ValueError):
    """Raised when an ETL record does not satisfy the expected schema."""


PATIENT_REQUIRED_FIELDS = (
    "patient_id",
    "mrn",
    "last_name",
    "first_name",
    "dob",
    "sex",
    "patient_address_id",
    "active",
)
ADDRESS_REQUIRED_FIELDS = (
    "address_id",
    "patient_id",
    "address_line1",
    "city",
    "state",
    "zip_code",
)
VISIT_REQUIRED_FIELDS = ("patient_visit_id", "patient_id", "visit_date")


def _is_missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().upper() in {"", "NULL"}
    )


def _require_fields(
    record: Mapping[str, Any], fields: tuple[str, ...], record_name: str
) -> None:
    missing = [field for field in fields if _is_missing(record.get(field))]
    if missing:
        raise SchemaValidationError(
            f"{record_name} is missing required field(s): {', '.join(missing)}"
        )


def validate_patient_and_address(payload: Mapping[str, Any]) -> None:
    """Validate patient and address source records independently of visits."""
    if not isinstance(payload, Mapping):
        raise SchemaValidationError("Payload must be a mapping.")

    patient = payload.get("patient")
    if not isinstance(patient, Mapping):
        raise SchemaValidationError("Payload must contain a patient mapping.")
    _require_fields(patient, PATIENT_REQUIRED_FIELDS, "patient")

    patient_id = patient["patient_id"]
    if (
        isinstance(patient_id, bool)
        or not isinstance(patient_id, int)
        or patient_id <= 0
    ):
        raise SchemaValidationError("patient.patient_id must be a positive integer.")

    active = patient["active"]
    if isinstance(active, bool):
        pass
    elif not isinstance(active, int) or active not in (0, 1):
        raise SchemaValidationError("patient.active must be 0, 1, or a boolean.")

    address = payload.get("address")
    if address not in (None, {}):
        if not isinstance(address, Mapping):
            raise SchemaValidationError("address must be a mapping or null.")
        _require_fields(address, ADDRESS_REQUIRED_FIELDS, "address")
        if (
            isinstance(address["address_id"], bool)
            or not isinstance(address["address_id"], int)
            or address["address_id"] <= 0
        ):
            raise SchemaValidationError("address.address_id must be a positive integer.")
        if address["patient_id"] != patient_id:
            raise SchemaValidationError("address.patient_id does not match patient_id.")


def validate_visit(
    visit: Mapping[str, Any], patient_id: int, *, index: int | None = None
) -> None:
    """Validate one visit so a bad visit need not reject its Patient."""
    label = "visit" if index is None else f"visits[{index}]"
    if not isinstance(visit, Mapping):
        raise SchemaValidationError(f"{label} must be a mapping.")
    _require_fields(visit, VISIT_REQUIRED_FIELDS, label)
    if (
        isinstance(visit["patient_visit_id"], bool)
        or not isinstance(visit["patient_visit_id"], int)
        or visit["patient_visit_id"] <= 0
    ):
        raise SchemaValidationError(
            f"{label}.patient_visit_id must be a positive integer."
        )
    if visit["patient_id"] != patient_id:
        raise SchemaValidationError(f"{label}.patient_id does not match patient_id.")


def validate_raw_payload(payload: Mapping[str, Any]) -> None:
    """Validate a complete raw aggregate for compatibility callers."""
    validate_patient_and_address(payload)
    patient = payload["patient"]
    patient_id = patient["patient_id"]
    visits = payload.get("visits", [])
    if isinstance(visits, (str, bytes)) or not isinstance(visits, Sequence):
        raise SchemaValidationError("visits must be a sequence.")
    for index, visit in enumerate(visits):
        validate_visit(visit, patient_id, index=index)
