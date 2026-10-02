"""Integration with the HL7-maintained FHIR Validator CLI."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..observability.retry import RetryPolicy, run_with_retry

VALIDATION_MODES = {"off", "if-available", "required"}


def _runtime_setting(name: str) -> str | None:
    """Read process environment first, then the repository .env file."""
    process_value = os.getenv(name)
    if process_value is not None:
        return process_value
    environment_path = Path(__file__).resolve().parents[2] / ".env"
    try:
        lines = environment_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            continue
        key, value = candidate.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'") or None
    return None


class OfficialFHIRValidationError(ValueError):
    """Raised when the official validator finds FHIR conformance errors."""


class OfficialValidatorConfigurationError(RuntimeError):
    """Raised when required validator tooling is not configured."""


class OfficialValidatorTechnicalError(RuntimeError):
    """Raised for retryable validator-process or output failures."""


@dataclass(frozen=True)
class OfficialValidatorConfig:
    mode: str = "if-available"
    jar_path: Path | None = None
    java_command: str = "java"
    timeout_seconds: float = 180.0
    implementation_guides: tuple[str, ...] = ()
    terminology_server: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in VALIDATION_MODES:
            raise ValueError(
                "Official validation mode must be off, if-available, or required."
            )
        if self.timeout_seconds <= 0:
            raise ValueError("Official validator timeout must be positive.")

    @classmethod
    def from_environment(
        cls,
        *,
        mode: str | None = None,
        jar_path: str | Path | None = None,
        timeout_seconds: float = 180.0,
        implementation_guides: Sequence[str] = (),
    ) -> "OfficialValidatorConfig":
        configured_path = jar_path or _runtime_setting("FHIR_VALIDATOR_JAR")
        return cls(
            mode=mode or _runtime_setting("FHIR_VALIDATOR_MODE") or "if-available",
            jar_path=Path(configured_path).resolve() if configured_path else None,
            java_command=_runtime_setting("FHIR_JAVA_COMMAND") or "java",
            timeout_seconds=timeout_seconds,
            implementation_guides=tuple(implementation_guides),
            terminology_server=_runtime_setting("FHIR_TERMINOLOGY_SERVER"),
        )


@dataclass(frozen=True)
class OfficialValidationResult:
    status: str
    validator: str = "HL7 FHIR Validator CLI"
    fhir_version: str = "4.0.1"
    attempts: int = 0
    duration_ms: float = 0.0
    issue_counts: dict[str, int] = field(default_factory=dict)
    implementation_guides: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["implementation_guides"] = list(self.implementation_guides)
        return payload


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class OfficialFHIRValidator:
    """Validate a generated Bundle against base R4 and configured IG packages."""

    def __init__(
        self,
        config: OfficialValidatorConfig,
        *,
        retry_policy: RetryPolicy | None = None,
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self.config = config
        self.retry_policy = retry_policy or RetryPolicy()
        self.command_runner = command_runner
        self.logger = logging.getLogger(__name__)

    def _availability_error(self) -> str | None:
        if self.config.jar_path is None:
            return "FHIR_VALIDATOR_JAR is not configured."
        if not self.config.jar_path.is_file():
            return "Configured FHIR Validator JAR does not exist."
        return None

    def _command(self, source_path: Path, outcome_path: Path) -> list[str]:
        assert self.config.jar_path is not None
        command = [
            self.config.java_command,
            "-jar",
            str(self.config.jar_path),
            str(source_path),
            "-version",
            "4.0.1",
            "-output",
            str(outcome_path),
        ]
        for implementation_guide in self.config.implementation_guides:
            command.extend(("-ig", implementation_guide))
        if self.config.terminology_server:
            command.extend(("-tx", self.config.terminology_server))
        return command

    @staticmethod
    def _parse_outcome(outcome_path: Path) -> Counter[str]:
        try:
            payload = json.loads(outcome_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OfficialValidatorTechnicalError(
                "The official validator did not produce a readable JSON outcome."
            ) from error
        if payload.get("resourceType") != "OperationOutcome":
            raise OfficialValidatorTechnicalError(
                "The official validator output was not an OperationOutcome."
            )
        counts: Counter[str] = Counter()
        for issue in payload.get("issue") or []:
            if isinstance(issue, Mapping):
                severity = str(issue.get("severity") or "unknown").lower()
                counts[severity] += 1
        return counts

    def validate(self, bundle: Mapping[str, Any]) -> OfficialValidationResult:
        if self.config.mode == "off":
            return OfficialValidationResult(
                status="SKIPPED_DISABLED",
                implementation_guides=self.config.implementation_guides,
                reason="Official validation was explicitly disabled.",
            )

        availability_error = self._availability_error()
        if availability_error:
            if self.config.mode == "required":
                raise OfficialValidatorConfigurationError(availability_error)
            return OfficialValidationResult(
                status="SKIPPED_UNAVAILABLE",
                implementation_guides=self.config.implementation_guides,
                reason=availability_error,
            )

        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="fhir-validator-") as directory:
            validation_directory = Path(directory)
            source_path = validation_directory / "bundle.json"
            outcome_path = validation_directory / "operation-outcome.json"
            source_path.write_text(
                json.dumps(bundle, ensure_ascii=False, allow_nan=False),
                encoding="utf-8",
            )
            command = self._command(source_path, outcome_path)

            def execute() -> tuple[subprocess.CompletedProcess[str], Counter[str]]:
                outcome_path.unlink(missing_ok=True)
                try:
                    process = self.command_runner(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=self.config.timeout_seconds,
                        check=False,
                    )
                except FileNotFoundError as error:
                    raise OfficialValidatorConfigurationError(
                        "The configured Java command was not found."
                    ) from error
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise OfficialValidatorTechnicalError(
                        "The official validator process could not complete."
                    ) from error
                counts = self._parse_outcome(outcome_path)
                errors = counts["fatal"] + counts["error"]
                if errors:
                    raise OfficialFHIRValidationError(
                        f"Official FHIR R4 validation found {errors} error(s)."
                    )
                if process.returncode != 0:
                    raise OfficialValidatorTechnicalError(
                        "The official validator process exited abnormally."
                    )
                return process, counts

            (_, counts), attempts = run_with_retry(
                execute,
                policy=self.retry_policy,
                retryable=lambda error: isinstance(
                    error, OfficialValidatorTechnicalError
                ),
                operation_name="official_fhir_validation",
                logger=self.logger,
            )

        return OfficialValidationResult(
            status="PASSED",
            attempts=attempts,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            issue_counts=dict(sorted(counts.items())),
            implementation_guides=self.config.implementation_guides,
        )
