"""Extractor module for reading patient data from SQLite."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Generator

from ..observability.retry import RetryPolicy, run_with_retry


class DataIntegrityError(ValueError):
    """Raised when database relationships violate the expected schema."""


class SQLiteExtractor:
    """Extracts relational patient data from a read-only SQLite database."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.retry_policy = retry_policy or RetryPolicy()
        self.logger = logging.getLogger(__name__)

    def _get_connection(self) -> sqlite3.Connection:
        """Create a read-only SQLite connection."""
        if not self.db_path.is_file():
            raise FileNotFoundError(f"SQLite database file not found at: {self.db_path}")

        # Use URI mode to enforce read-only access safely
        uri = f"{self.db_path.as_uri()}?mode=ro"
        (conn, _) = run_with_retry(
            lambda: sqlite3.connect(uri, uri=True),
            policy=self.retry_policy,
            retryable=lambda error: isinstance(error, sqlite3.OperationalError),
            operation_name="sqlite_connect",
            logger=self.logger,
        )
        conn.row_factory = sqlite3.Row
        
        # Enforce read-only at the database engine level
        conn.execute("PRAGMA query_only = ON;")
        return conn

    def iter_patients(self) -> Generator[Dict[str, Any], None, None]:
        """
        Extract patient records using 3 deterministic batch queries.
        
        Yields patient payloads iteratively to maintain low memory footprint.
        """
        self.logger.info("Connecting to database at %s", self.db_path)

        with closing(self._get_connection()) as conn:
            cursor = conn.cursor()

            violations = cursor.execute("PRAGMA foreign_key_check;").fetchall()
            if violations:
                raise DataIntegrityError(
                    f"Database contains {len(violations)} foreign-key violation(s)."
                )

            # 1. Fetch all patients in deterministic order
            self.logger.debug("Fetching patient records...")
            cursor.execute("SELECT * FROM patient ORDER BY patient_id ASC;")
            patients = [dict(row) for row in cursor.fetchall()]

            if not patients:
                self.logger.info("No patient records found in database.")
                return

            # 2. Fetch all addresses and index by patient_id
            self.logger.debug("Fetching address records...")
            cursor.execute("SELECT * FROM patient_address ORDER BY address_id ASC;")
            addresses_by_patient: Dict[int, Dict[str, Any]] = {}
            for row in cursor.fetchall():
                addr_dict = dict(row)
                patient_id = addr_dict["patient_id"]
                if patient_id in addresses_by_patient:
                    raise DataIntegrityError(
                        f"Expected one address for patient {patient_id}, "
                        "but multiple addresses were found."
                    )
                addresses_by_patient[patient_id] = addr_dict

            # 3. Fetch all visits and group by patient_id
            self.logger.debug("Fetching visit records...")
            cursor.execute(
                "SELECT * FROM patient_visit ORDER BY patient_id ASC, visit_date ASC, patient_visit_id ASC;"
            )
            visits_by_patient: Dict[int, List[Dict[str, Any]]] = {}
            for row in cursor.fetchall():
                visit_dict = dict(row)
                pid = visit_dict["patient_id"]
                visits_by_patient.setdefault(pid, []).append(visit_dict)

        # Assemble and yield unified raw payloads
        count = 0
        for patient in patients:
            pid = patient["patient_id"]
            payload = {
                "patient": patient,
                "address": addresses_by_patient.get(pid),
                "visits": visits_by_patient.get(pid, []),
            }
            count += 1
            yield payload

        self.logger.info("Successfully extracted %d patient records.", count)

    def extract_all_patients(self) -> List[Dict[str, Any]]:
        """Return all extracted patient records as a list."""
        return list(self.iter_patients())
