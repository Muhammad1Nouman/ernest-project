"""Atomically stream transformed records to a JSON document."""

from __future__ import annotations
import json
import logging
import os
import stat
import tempfile
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..observability.retry import RetryPolicy, run_with_retry

class FHIRArtifactLoader:
    """Atomically publish a FHIR Bundle and its operational sidecars."""

    def __init__(
        self,
        output_path: str | Path,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.output_path = Path(output_path).resolve()
        suffix = self.output_path.suffix or ".json"
        stem = self.output_path.stem
        self.rejected_path = self.output_path.with_name(f"{stem}.rejected{suffix}")
        self.lineage_path = self.output_path.with_name(f"{stem}.lineage{suffix}")
        self.summary_path = self.output_path.with_name(f"{stem}.summary{suffix}")
        self.retry_policy = retry_policy or RetryPolicy()
        self.logger = logging.getLogger(__name__)

    def _with_io_retry(self, operation, operation_name: str):
        result, _ = run_with_retry(
            operation,
            policy=self.retry_policy,
            retryable=lambda error: isinstance(error, OSError),
            operation_name=operation_name,
            logger=self.logger,
        )
        return result

    @staticmethod
    def _stage_json(path: Path, payload: Any) -> Path:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            try:
                os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return temporary_path
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary_path.unlink(missing_ok=True)
            raise

    def load_artifacts(
        self,
        *,
        bundle: Mapping[str, Any],
        rejected: Iterable[Mapping[str, Any]],
        lineage: Iterable[Mapping[str, Any]],
        summary: Mapping[str, Any],
    ) -> dict[str, Path]:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        staged: dict[Path, Path] = {}
        started = time.perf_counter()
        rejected_payload = list(rejected)
        lineage_payload = list(lineage)
        try:
            staged[self.rejected_path] = self._with_io_retry(
                lambda: self._stage_json(self.rejected_path, rejected_payload),
                "stage_rejected_artifact",
            )
            staged[self.lineage_path] = self._with_io_retry(
                lambda: self._stage_json(self.lineage_path, lineage_payload),
                "stage_lineage_artifact",
            )
            staged[self.output_path] = self._with_io_retry(
                lambda: self._stage_json(self.output_path, dict(bundle)),
                "stage_fhir_bundle",
            )
            summary_payload = dict(summary)
            summary_payload["stage_durations_ms"] = dict(
                summary_payload.get("stage_durations_ms", {})
            )
            summary_payload["stage_durations_ms"]["output"] = round(
                (time.perf_counter() - started) * 1000, 3
            )
            staged[self.summary_path] = self._with_io_retry(
                lambda: self._stage_json(self.summary_path, summary_payload),
                "stage_run_summary",
            )
            # The summary is the commit marker and is published last.
            for destination in (
                self.rejected_path,
                self.lineage_path,
                self.output_path,
                self.summary_path,
            ):
                self._with_io_retry(
                    lambda destination=destination: os.replace(
                        staged[destination], destination
                    ),
                    "publish_artifact",
                )
            self.logger.info(
                "Published FHIR Bundle and operational artifacts",
                extra={"event": "artifacts_published", "stage": "LOAD", "count": len(bundle.get("entry", []))},
            )
            return {
                "output": self.output_path,
                "rejected": self.rejected_path,
                "lineage": self.lineage_path,
                "summary": self.summary_path,
            }
        finally:
            for temporary_path in staged.values():
                temporary_path.unlink(missing_ok=True)
