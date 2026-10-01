"""Atomically stream transformed records to a JSON document."""

from __future__ import annotations
import json
import logging
import os
import stat
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

class JSONLoader:
    """Write transformed data to a permission-restricted JSON file."""

    def __init__(self, output_path: str | Path) -> None:
        self.output_path = Path(output_path)
        self.logger = logging.getLogger(__name__)

    def load(self, data: Iterable[Mapping[str, Any]]) -> int:
        """Stream records to a temporary file and atomically replace the output."""
        output_path = self.output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info("Serializing transformed data to %s", output_path)

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

                # Set POSIX owner-only permissions (0600) BEFORE moving into place
                try:
                    os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    self.logger.warning("Could not restrict permissions on temp file %s", temporary_path)

                temporary_file.write("[\n")

                for record in data:
                    if count:
                        temporary_file.write(",\n")

                    # Indent record payload cleanly without splitting/joining lines
                    serialized = json.dumps(
                        dict(record), indent=2, ensure_ascii=False, allow_nan=False
                    )
                    
                    # Prefix indented lines efficiently
                    indented_record = "  " + serialized.replace("\n", "\n  ")
                    temporary_file.write(indented_record)
                    count += 1

                temporary_file.write("\n]\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            # Atomic swap ensures zero partial-write exposure
            os.replace(temporary_path, output_path)
            completed = True

            self.logger.info("Successfully exported %d JSON records to %s", count, output_path)
            return count

        except Exception:
            self.logger.exception("Failed to save JSON output to %s", output_path)
            raise
        finally:
            if not completed and temporary_path is not None:
                temporary_path.unlink(missing_ok=True)