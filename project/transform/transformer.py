"""Transform validated database records into the public JSON shape."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from .schemas import validate_raw_payload


class DataTransformer:
    """Class responsible for transforming relational SQL data into JSON-ready structure."""

    def __init__(self) -> None:
        self.logger: logging.Logger = logging.getLogger(__name__)

    @staticmethod
    def _clean_field(value: Any) -> Any | None:
        """Normalize null-like values and surrounding string whitespace."""
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned or cleaned.upper() in {"NULL", "NONE", "N/A"}:
                return None
            return cleaned
        return value

    @classmethod
    def _mask_ssn(cls, value: Any) -> str | None:
        """Retain only the last four SSN digits in exported data."""
        cleaned = cls._clean_field(value)
        if cleaned is None:
            return None
        
        digits = "".join(char for char in str(cleaned) if char.isdigit())
        if len(digits) == 9:
            return f"***-**-{digits[-4:]}"
        elif len(digits) >= 4:
            return f"***-**-{digits[-4:]}"
        return "REDACTED"

    def transform_single(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Transforms raw SQL rows for a single patient into a nested dictionary."""
        validate_raw_payload(payload)
        patient = payload["patient"]
        address = payload.get("address")
        visits = payload.get("visits") or []

        # Construct nested address object only if valid fields exist
        transformed_address: dict[str, Any] | None = None
        if address and any(v is not None for v in address.values()):
            transformed_address = {
                "address_id": address.get("address_id"),
                "address_line1": self._clean_field(address.get("address_line1")),
                "address_line2": self._clean_field(address.get("address_line2")),
                "city": self._clean_field(address.get("city")),
                "state": self._clean_field(address.get("state")),
                "zip_code": self._clean_field(address.get("zip_code")),
            }

        # Construct nested list of visit objects
        transformed_visits: list[dict[str, Any]] = [
            {
                "patient_visit_id": v.get("patient_visit_id"),
                "visit_date": self._clean_field(v.get("visit_date")),
                "symptoms": self._clean_field(v.get("symptoms")),
                "prescription": self._clean_field(v.get("prescription")),
            }
            for v in visits
        ]

        # Assemble clean record with all string fields cleaned
        return {
            "patient_id": patient.get("patient_id"),
            "mrn": self._clean_field(patient.get("mrn")),
            "first_name": self._clean_field(patient.get("first_name")),
            "middle_name": self._clean_field(patient.get("middle_name")),
            "last_name": self._clean_field(patient.get("last_name")),
            "suffix": self._clean_field(patient.get("suffix")),
            "dob": self._clean_field(patient.get("dob")),
            "sex": self._clean_field(patient.get("sex")),
            "ssn": self._mask_ssn(patient.get("ssn")),
            "patient_address_id": patient.get("patient_address_id"),
            "home_phone": self._clean_field(patient.get("home_phone")),
            "mobile_phone": self._clean_field(patient.get("mobile_phone")),
            "email": self._clean_field(patient.get("email")),
            "language": self._clean_field(patient.get("language")),
            "marital_status": self._clean_field(patient.get("marital_status")),
            "deceased_date": self._clean_field(patient.get("deceased_date")),
            "active": bool(patient.get("active")),
            "address": transformed_address,
            "visits": transformed_visits,
        }

    def transform_iter(
        self, payloads: Iterable[Mapping[str, Any]]
    ) -> Iterator[dict[str, Any]]:
        """Validate and transform records without materializing the full dataset."""
        count = 0
        for payload in payloads:
            yield self.transform_single(payload)
            count += 1
        self.logger.info("Finished streaming transformation of %d records.", count)

    def transform_batch(
        self, payloads: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """Compatibility helper for callers that require a list."""
        return list(self.transform_iter(payloads))
