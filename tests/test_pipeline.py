"""Regression tests for correctness, safety, and deterministic output."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from project.extract.extractor import DataIntegrityError, SQLiteExtractor
from project.main import main, run_pipeline
from project.transform.schemas import SchemaValidationError
from project.transform.transformer import DataTransformer
from sqlite_seed import seed_database


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        logging.shutdown()
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()
        self.temporary_directory.cleanup()

    def test_end_to_end_output_is_ordered_streamed_and_redacted(self) -> None:
        database = seed_database(self.root / "patients.db")
        output = self.root / "patients.json"
        log = self.root / "pipeline.log"

        count = run_pipeline(database, output, log)

        self.assertEqual(count, 10)
        records = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(
            [record["patient_id"] for record in records],
            list(range(10042, 10052)),
        )
        self.assertTrue(all(record["ssn"].startswith("***-**-") for record in records))
        self.assertNotIn("123-45-6789", output.read_text(encoding="utf-8"))
        self.assertTrue(all(isinstance(record["active"], bool) for record in records))
        self.assertTrue(all(len(record["visits"]) == 2 for record in records))
        self.assertTrue(all(record["patient_address_id"] for record in records))
        self.assertEqual(list(self.root.glob(".patients.json.*.tmp")), [])

        with closing(sqlite3.connect(database)) as connection:
            patient_foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(patient)"
            ).fetchall()
        self.assertTrue(
            any(
                foreign_key[2:5]
                == ("patient_address", "patient_address_id", "address_id")
                for foreign_key in patient_foreign_keys
            )
        )

    def test_cli_prints_the_generated_json_string(self) -> None:
        database = seed_database(self.root / "cli-patients.db")
        output = self.root / "cli-patients.json"
        log = self.root / "cli-pipeline.log"
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = main(
                ["--db", str(database), "--output", str(output), "--log", str(log)]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), json.loads(output.read_text()))

    def test_missing_database_is_not_created(self) -> None:
        missing = self.root / "missing.db"
        with self.assertRaises(FileNotFoundError):
            list(SQLiteExtractor(missing).iter_patients())
        self.assertFalse(missing.exists())

    def test_invalid_patient_is_rejected_instead_of_exported(self) -> None:
        payload = {
            "patient": {"patient_id": "not-an-integer"},
            "address": None,
            "visits": [],
        }
        with self.assertRaises(SchemaValidationError):
            DataTransformer().transform_single(payload)

    def test_multiple_addresses_are_rejected(self) -> None:
        database = self.root / "duplicate-address.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript(
                """
                CREATE TABLE patient (
                    patient_id INTEGER PRIMARY KEY, mrn TEXT, last_name TEXT,
                    first_name TEXT, middle_name TEXT, suffix TEXT, dob TEXT,
                    sex TEXT, ssn TEXT, home_phone TEXT, mobile_phone TEXT,
                    email TEXT, language TEXT, marital_status TEXT,
                    deceased_date TEXT, active INTEGER
                );
                CREATE TABLE patient_address (
                    address_id INTEGER PRIMARY KEY, patient_id INTEGER,
                    address_line1 TEXT, address_line2 TEXT, city TEXT,
                    state TEXT, zip_code TEXT,
                    FOREIGN KEY (patient_id) REFERENCES patient(patient_id)
                );
                CREATE TABLE patient_visit (
                    patient_visit_id INTEGER PRIMARY KEY, patient_id INTEGER,
                    visit_date TEXT, symptoms TEXT, prescription TEXT,
                    FOREIGN KEY (patient_id) REFERENCES patient(patient_id)
                );
                INSERT INTO patient VALUES (
                    1, 'MRN-1', 'DOE', 'JANE', NULL, NULL, '2000-01-01',
                    'F', '111-22-3333', NULL, NULL, NULL, NULL, NULL, NULL, 1
                );
                INSERT INTO patient_address VALUES
                    (1, 1, 'One St', NULL, 'Boston', 'MA', '02110'),
                    (2, 1, 'Two St', NULL, 'Boston', 'MA', '02111');
                """
            )
            connection.commit()

        with self.assertRaises(DataIntegrityError):
            list(SQLiteExtractor(database).iter_patients())


if __name__ == "__main__":
    unittest.main()
