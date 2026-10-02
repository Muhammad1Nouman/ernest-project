"""Agentic normalization followed by deterministic FHIR R4 mapping."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ..extract.extractor import SQLiteExtractor
from ..fhir.finalize import finalize_run
from ..fhir.processor import FHIRRunAccumulator
from ..fhir.terminology import map_gender
from ..observability.errors import RecordProcessingError
from ..observability.alerts import AlertThresholds
from ..observability.logging import set_log_context
from ..observability.models import PipelineResult, RunContext
from ..observability.retry import RetryPolicy
from ..transform.normalizer import SourceNormalizer
from ..validation.official_validator import (
    OfficialFHIRValidator,
    OfficialValidatorConfig,
)
from .agent_transformer import AIAgentTransformer


def batched(
    records: list[tuple[dict[str, Any], dict[str, Any]]], batch_size: int
) -> Iterator[list[tuple[dict[str, Any], dict[str, Any]]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    for start in range(0, len(records), batch_size):
        yield records[start : start + batch_size]


def _merge_agent_display_values(
    normalized: dict[str, Any], agent_result: Mapping[str, Any]
) -> dict[str, Any]:
    """Accept display normalization while protecting authoritative semantics."""
    patient = normalized["patient"]
    if agent_result.get("patient_id") != patient["patient_id"]:
        raise RecordProcessingError(
            "SYSTEM_MODEL_ID_MISMATCH",
            "Agent response patient identifier did not match the source.",
            stage="AGENT_VALIDATION",
            field="patient_id",
        )
    if agent_result.get("mrn") != patient["mrn"]:
        raise RecordProcessingError(
            "SYSTEM_MODEL_ID_MISMATCH",
            "Agent response MRN did not match the source.",
            stage="AGENT_VALIDATION",
            field="mrn",
        )
    if str(agent_result.get("dob")) != patient["birth_date"]:
        raise RecordProcessingError(
            "SYSTEM_MODEL_VALUE_MISMATCH",
            "Agent response birth date did not match deterministic normalization.",
            stage="AGENT_VALIDATION",
            field="birthDate",
        )
    if bool(agent_result.get("is_active")) != patient["active"]:
        raise RecordProcessingError(
            "SYSTEM_MODEL_VALUE_MISMATCH",
            "Agent response active flag did not match the source.",
            stage="AGENT_VALIDATION",
            field="active",
        )

    if map_gender(agent_result.get("gender")) != map_gender(patient["gender_source"]):
        raise RecordProcessingError(
            "SYSTEM_MODEL_VALUE_MISMATCH",
            "Agent response gender did not match deterministic terminology mapping.",
            stage="AGENT_VALIDATION",
            field="gender",
        )
    patient["display_name"] = agent_result.get("full_name")
    source_visits = normalized.get("visits") or []
    agent_visits = agent_result.get("visits") or []
    source_visit_pairs = [
        (visit["patient_visit_id"], visit["start"]) for visit in source_visits
    ]
    agent_visit_pairs = [
        (visit.get("patient_visit_id"), str(visit.get("visit_date")))
        for visit in agent_visits
    ]
    if agent_visit_pairs != source_visit_pairs:
        raise RecordProcessingError(
            "SYSTEM_MODEL_VALUE_MISMATCH",
            "Agent response visit identities, dates, or ordering changed.",
            stage="AGENT_VALIDATION",
            field="visits",
        )

    source_address = normalized.get("address")
    agent_address = agent_result.get("address")
    if source_address is None and agent_address is not None:
        raise RecordProcessingError(
            "SYSTEM_MODEL_VALUE_MISMATCH",
            "Agent invented an address that was absent from the source.",
            stage="AGENT_VALIDATION",
            field="address",
        )
    if source_address is not None:
        if not isinstance(agent_address, Mapping) or agent_address.get(
            "address_id"
        ) != source_address.get("address_id"):
            raise RecordProcessingError(
                "SYSTEM_MODEL_ID_MISMATCH",
                "Agent response address identifier did not match the source.",
                stage="AGENT_VALIDATION",
                field="address.address_id",
            )
        source_address["display_text"] = agent_address.get("street_address")
    return normalized


async def run_agentic_etl(
    db_path: str | Path,
    output_path: str | Path,
    *,
    batch_size: int = 25,
    concurrency: int = 5,
    model_name: str = "gemini-3.5-flash-lite",
    max_attempts: int = 3,
    request_timeout_seconds: float = 60.0,
    transformer: AIAgentTransformer | None = None,
    run_id: str | None = None,
    retry_policy: RetryPolicy | None = None,
    official_validator_config: OfficialValidatorConfig | None = None,
    official_validator: OfficialFHIRValidator | None = None,
    alert_thresholds: AlertThresholds | None = None,
) -> PipelineResult:
    """Use ADK for display normalization, then deterministic FHIR controls."""
    logger = logging.getLogger("Agentic_FHIR_ETL")
    context = RunContext.create("agentic", run_id)
    set_log_context(context.run_id, context.implementation)
    active_retry_policy = retry_policy or RetryPolicy()
    extractor = SQLiteExtractor(db_path, retry_policy=active_retry_policy)
    normalizer = SourceNormalizer()
    active_transformer = transformer or AIAgentTransformer(
        model_name=model_name,
        concurrency_limit=concurrency,
        max_attempts=max_attempts,
        request_timeout_seconds=request_timeout_seconds,
    )
    accumulator = FHIRRunAccumulator(context)

    logger.info(
        "Starting agentic-normalized FHIR R4 ETL",
        extra={
            "event": "run_started",
            "run_id": context.run_id,
            "implementation": context.implementation,
            "stage": "START",
        },
    )
    extraction_started = time.perf_counter()
    payloads = list(extractor.iter_patients())
    extraction_ms = (time.perf_counter() - extraction_started) * 1000
    source_counts = {
        "patient": len(payloads),
        "patient_address": sum(1 for payload in payloads if payload.get("address")),
        "patient_visit": sum(len(payload.get("visits") or []) for payload in payloads),
    }

    prepared: list[tuple[dict[str, Any], dict[str, Any]]] = []
    normalization_started = time.perf_counter()
    for raw_payload in payloads:
        accumulator.register_source_payload(raw_payload)
        try:
            normalized = normalizer.normalize_patient(raw_payload)
        except RecordProcessingError as error:
            accumulator.reject_patient_tree(raw_payload, error)
            continue

        valid_raw_visits: list[dict[str, Any]] = []
        normalized_visits: list[dict[str, Any]] = []
        source_patient_id = raw_payload["patient"]["patient_id"]
        for raw_visit in raw_payload.get("visits") or []:
            try:
                visit = normalizer.normalize_visit(
                    raw_visit, patient_id=source_patient_id
                )
            except RecordProcessingError as error:
                accumulator.reject_visit(raw_visit, error)
                continue
            valid_raw_visits.append(dict(raw_visit))
            normalized_visits.append(visit)
        normalized["visits"] = normalized_visits
        sanitized_payload = {
            "patient": raw_payload["patient"],
            "address": raw_payload.get("address"),
            "visits": valid_raw_visits,
        }
        prepared.append((sanitized_payload, normalized))
    normalization_ms = (time.perf_counter() - normalization_started) * 1000

    agent_started = time.perf_counter()
    for batch_number, batch in enumerate(batched(prepared, batch_size), start=1):
        logger.info(
            "Normalizing bounded ADK batch",
            extra={
                "event": "batch_started",
                "run_id": context.run_id,
                "implementation": context.implementation,
                "stage": "AGENT_NORMALIZATION",
                "count": len(batch),
            },
        )
        raw_batch = [item[0] for item in batch]
        results = await active_transformer.transform_batch_with_errors_async(raw_batch)
        for (raw_payload, normalized), result in zip(batch, results, strict=True):
            if isinstance(result, BaseException):
                model_error = RecordProcessingError(
                    "SYSTEM_MODEL_FAILURE",
                    "Model normalization failed after configured retries.",
                    stage="AGENT_NORMALIZATION",
                    retryable=True,
                )
                accumulator.reject_patient_tree(raw_payload, model_error)
                continue
            try:
                merged = _merge_agent_display_values(normalized, result)
            except RecordProcessingError as error:
                accumulator.reject_patient_tree(raw_payload, error)
                continue
            patient_id = accumulator.process_patient(merged, raw_payload)
            if patient_id is None:
                continue
            for visit, raw_visit in zip(
                merged.get("visits") or [],
                raw_payload.get("visits") or [],
                strict=True,
            ):
                accumulator.process_visit(
                    visit, raw_visit, patient_id=patient_id
                )
    agent_ms = (time.perf_counter() - agent_started) * 1000

    return finalize_run(
        context=context,
        accumulator=accumulator,
        source_counts=source_counts,
        output_path=output_path,
        stage_durations_ms={
            "extraction": extraction_ms,
            "normalization": normalization_ms,
            "agent_normalization": agent_ms,
        },
        retry_policy=active_retry_policy,
        official_validator_config=official_validator_config,
        official_validator=official_validator,
        alert_thresholds=alert_thresholds,
    )
