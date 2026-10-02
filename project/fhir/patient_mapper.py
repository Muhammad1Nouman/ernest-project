"""Map normalized source data to a base FHIR R4 Patient resource."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .identifiers import PATIENT_MRN_SYSTEM, source_integer_id
from .terminology import map_gender
from ..observability.errors import RecordProcessingError
from ..observability.models import PATIENT_MAPPING_VERSION


def _required(value: Any, field: str) -> str:
    if value is None or not str(value).strip():
        raise RecordProcessingError(
            "SRC_REQUIRED_FIELD_MISSING",
            f"Required normalized field '{field}' is missing.",
            stage="FHIR_MAPPING",
            field=field,
        )
    return str(value).strip()


def map_patient(normalized: Mapping[str, Any]) -> dict[str, Any]:
    patient = normalized["patient"]
    patient_id = source_integer_id(patient.get("patient_id"), "patient_id")
    given = [_required(patient.get("first_name"), "first_name")]
    if patient.get("middle_name"):
        given.append(str(patient["middle_name"]))
    name: dict[str, Any] = {
        "use": "official",
        "family": _required(patient.get("last_name"), "last_name"),
        "given": given,
    }
    if patient.get("display_name"):
        name["text"] = str(patient["display_name"])
    if patient.get("suffix"):
        name["suffix"] = [str(patient["suffix"])]

    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/Patient"],
            "tag": [
                {
                    "system": "https://example.org/fhir/mapping-version",
                    "code": PATIENT_MAPPING_VERSION,
                }
            ],
        },
        "identifier": [
            {
                "use": "usual",
                "system": PATIENT_MRN_SYSTEM,
                "value": _required(patient.get("mrn"), "mrn"),
            }
        ],
        "active": patient.get("active"),
        "name": [name],
        "gender": map_gender(patient.get("gender_source")),
        "birthDate": _required(patient.get("birth_date"), "birth_date"),
    }

    telecom = []
    for field, system, use in (
        ("home_phone", "phone", "home"),
        ("mobile_phone", "phone", "mobile"),
        ("email", "email", "home"),
    ):
        if patient.get(field):
            telecom.append(
                {"system": system, "value": str(patient[field]), "use": use}
            )
    if telecom:
        resource["telecom"] = telecom

    address = normalized.get("address")
    if isinstance(address, Mapping):
        mapped_address: dict[str, Any] = {
            "use": "home",
            "type": "physical",
            "line": list(address.get("lines") or []),
            "city": _required(address.get("city"), "address.city"),
            "state": _required(address.get("state"), "address.state"),
            "postalCode": _required(
                address.get("postal_code"), "address.postal_code"
            ),
        }
        if address.get("display_text"):
            mapped_address["text"] = str(address["display_text"])
        resource["address"] = [mapped_address]
    return resource

