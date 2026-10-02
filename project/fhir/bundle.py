"""FHIR R4 collection Bundle construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .identifiers import full_url


def build_collection_bundle(
    resources: Iterable[Mapping[str, Any]], *, run_id: str, timestamp: str
) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "id": run_id,
        "meta": {"profile": ["http://hl7.org/fhir/StructureDefinition/Bundle"]},
        "type": "collection",
        "timestamp": timestamp,
        "entry": [
            {
                "fullUrl": full_url(
                    str(resource["resourceType"]), str(resource["id"])
                ),
                "resource": dict(resource),
            }
            for resource in resources
        ],
    }

