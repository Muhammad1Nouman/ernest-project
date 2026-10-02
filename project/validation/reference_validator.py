"""Business validation for references between generated FHIR resources."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..fhir.identifiers import full_url
from ..observability.errors import RecordProcessingError


def validate_references(resources: Iterable[Mapping[str, Any]]) -> None:
    materialized = list(resources)
    patients = {
        full_url("Patient", str(resource["id"]))
        for resource in materialized
        if resource.get("resourceType") == "Patient"
    }
    for resource in materialized:
        if resource.get("resourceType") != "Encounter":
            continue
        reference = (resource.get("subject") or {}).get("reference")
        if reference not in patients:
            raise RecordProcessingError(
                "FHIR_INVALID_REFERENCE",
                "Encounter subject does not resolve to a generated Patient.",
                stage="REFERENCE_VALIDATION",
                field="subject.reference",
            )
