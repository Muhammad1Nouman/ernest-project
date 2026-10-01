"""Atomic JSON loader for an asynchronous stream of agent-normalized records."""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from collections.abc import AsyncIterable, Mapping
from pathlib import Path
from typing import Any


class AsyncJSONLoader:
    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)
        self.logger = logging.getLogger(__name__)

    async def load_async(self, data: AsyncIterable[Mapping[str, Any]]) -> int:
        """Consume an async record stream into an atomically replaced JSON file."""
        output_path = self.output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        completed = False
        count = 0

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{output_path.name}.",
                suffix=".tmp",
                dir=output_path.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                try:
                    os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    self.logger.warning(
                        "Could not restrict permissions on %s", temporary_path
                    )

                temporary_file.write("[\n")
                async for record in data:
                    if count:
                        temporary_file.write(",\n")
                    serialized = json.dumps(
                        dict(record), indent=2, ensure_ascii=False, allow_nan=False
                    )
                    temporary_file.write("  " + serialized.replace("\n", "\n  "))
                    count += 1
                temporary_file.write("\n]\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, output_path)
            completed = True
            self.logger.info("Exported %d agent-normalized records to %s", count, output_path)
            return count
        except Exception:
            self.logger.exception("Failed to save agentic ETL JSON to %s", output_path)
            raise
        finally:
            if not completed and temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
