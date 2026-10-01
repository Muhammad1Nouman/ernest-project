"""Strict structured-output contracts for the patient normalization agent."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    """Base model that rejects fields outside the documented output contract."""

    model_config = ConfigDict(extra="forbid")


class AddressSchema(StrictSchema):
    address_id: int = Field(gt=0)
    street_address: str = Field(
        min_length=1, description="Normalized street address, including line 2 when present."
    )
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    zip_code: str = Field(min_length=1)

    @field_validator("street_address", "city", "state", "zip_code")
    @classmethod
    def strip_address_fields(cls, value: str) -> str:
        return value.strip()


class VisitSchema(StrictSchema):
    patient_visit_id: int = Field(gt=0)
    visit_date: date = Field(description="ISO-8601 calendar date.")


class TransformedPatientSchema(StrictSchema):
    patient_id: int = Field(gt=0)
    full_name: str = Field(min_length=1, description="Normalized full patient name.")
    mrn: str = Field(min_length=1)
    dob: date = Field(description="ISO-8601 date of birth.")
    gender: Literal["Male", "Female", "Other", "Unknown"]
    is_active: bool
    address: AddressSchema | None = None
    visits: list[VisitSchema] = Field(default_factory=list)

    @field_validator("full_name", "mrn")
    @classmethod
    def strip_patient_fields(cls, value: str) -> str:
        return value.strip()
