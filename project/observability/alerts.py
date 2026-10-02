"""Configurable operational alert thresholds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertThresholds:
    max_rejection_rate: float = 0.02
    max_duration_ms: float | None = 60_000.0
    minimum_patients: int = 1
    minimum_encounters: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.max_rejection_rate <= 1:
            raise ValueError("max_rejection_rate must be between 0 and 1.")
        if self.max_duration_ms is not None and self.max_duration_ms <= 0:
            raise ValueError("max_duration_ms must be positive when configured.")
        if self.minimum_patients < 0 or self.minimum_encounters < 0:
            raise ValueError("Minimum resource-count thresholds cannot be negative.")
