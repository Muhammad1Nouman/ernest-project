"""Categorized, PHI-safe record errors used by both FHIR pipelines."""

from __future__ import annotations


class RecordProcessingError(ValueError):
    """A record-level error that can be written safely to quarantine."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str,
        field: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.field = field
        self.retryable = retryable


class PipelineConfigurationError(RuntimeError):
    """A fatal configuration error that makes the complete run unsafe."""

