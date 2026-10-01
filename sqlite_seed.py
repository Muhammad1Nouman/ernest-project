"""Create a deterministic sample SQLite database safely."""

from __future__ import annotations

import argparse
import os
import sqlite3
import stat
import tempfile
from contextlib import closing
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().with_name("sqltojson.db")


def seed_database(
    db_path: str | Path = DEFAULT_DB_PATH, *, overwrite: bool = False
) -> Path:
    """Build a complete database, replacing an existing file only on success."""
    destination = Path(db_path).resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"Database already exists: {destination}. Use --force to replace it."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary_path = Path(temporary_name)

    try:
        with closing(sqlite3.connect(temporary_path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON;")
            cursor = connection.cursor()

            cursor.execute("""
    CREATE TABLE patient (
        patient_id INTEGER PRIMARY KEY,
        mrn TEXT NOT NULL,
        last_name TEXT NOT NULL,
        first_name TEXT NOT NULL,
        middle_name TEXT,
        suffix TEXT,
        dob TEXT NOT NULL,
        sex TEXT NOT NULL,
        ssn TEXT NOT NULL,
        patient_address_id INTEGER NOT NULL UNIQUE,
        home_phone TEXT,
        mobile_phone TEXT,
        email TEXT,
        language TEXT,
        marital_status TEXT,
        deceased_date TEXT,
        active INTEGER NOT NULL,
        FOREIGN KEY (patient_address_id) REFERENCES patient_address(address_id)
            DEFERRABLE INITIALLY DEFERRED
    );
    """)

            cursor.execute("""
    CREATE TABLE patient_address (
        address_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL UNIQUE,
        address_line1 TEXT NOT NULL,
        address_line2 TEXT,
        city TEXT NOT NULL,
        state TEXT NOT NULL,
        zip_code TEXT NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES patient(patient_id) ON DELETE CASCADE
    );
    """)

            cursor.execute("""
    CREATE TABLE patient_visit (
        patient_visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL,
        visit_date TEXT NOT NULL,
        symptoms TEXT,
        prescription TEXT,
        FOREIGN KEY (patient_id) REFERENCES patient(patient_id) ON DELETE CASCADE
    );
    """)

            cursor.execute("""
    CREATE INDEX idx_patient_visit_patient_date
    ON patient_visit (patient_id, visit_date, patient_visit_id);
    """)

            first_names = ["Maria", "James", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth"]
            last_names = ["ALVAREZ", "SMITH", "JONES", "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ"]
            cities = ["Boston", "Cambridge", "Somerville", "Quincy", "Newton", "Brookline", "Waltham", "Malden", "Medford", "Revere"]
            symptoms_list = [
        "Fever and dry cough", 
        "Severe headache and nausea", 
        "Routine physical checkup", 
        "Joint pain and fatigue", 
        "Mild hypertension follow-up"
            ]

            for i in range(10):
                patient_id = 10042 + i
                mrn = f"MRN-882{13 + i}"
                first_name = first_names[i]
                last_name = last_names[i]
                ssn = f"123-45-{6789 + i}"
                address_id = i + 1

                cursor.execute("""
        INSERT INTO patient (
            patient_id, mrn, last_name, first_name, middle_name, suffix,
            dob, sex, ssn, patient_address_id, home_phone, mobile_phone,
            email, language, marital_status, deceased_date, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            patient_id,
            mrn,
            last_name,
            first_name,
            "Elena" if i % 2 == 0 else None,
            None,
            "1978-04-12 00:00:00",
            "F" if i % 2 == 0 else "M",
            ssn,
            address_id,
            f"(508) 555-01{42 + i:02d}",
            "",
            f"{first_name[0]}.{last_name}@Example.COM",
            "Portuguese" if i == 0 else "English",
            "Married" if i % 3 == 0 else "Single",
            None,
            1
                ))

                cursor.execute("""
        INSERT INTO patient_address (
            address_id, patient_id, address_line1, address_line2, city, state, zip_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
            address_id,
            patient_id,
            f"{100 + i * 5} Main St",
            f"Apt {i + 1}" if i % 2 == 0 else "",
            cities[i],
            "MA",
            f"021{10 + i:02d}"
                ))

                for v in range(2):
                    cursor.execute("""
            INSERT INTO patient_visit (
                patient_id, visit_date, symptoms, prescription
            ) VALUES (?, ?, ?, ?);
                    """, (
                patient_id,
                f"2026-0{8 + v}-15 10:30:00",
                symptoms_list[(i + v) % len(symptoms_list)],
                "Amoxicillin 500mg" if v == 0 else "Ibuprofen 200mg"
                    ))

            connection.commit()
            violations = connection.execute("PRAGMA foreign_key_check;").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"Seeded database has {len(violations)} foreign-key violation(s)."
                )

        os.replace(temporary_path, destination)
        try:
            os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return destination
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--force", action="store_true", help="Atomically replace an existing database."
    )
    args = parser.parse_args(argv)

    try:
        destination = seed_database(args.db, overwrite=args.force)
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f"Database seed failed: {error}\n")

    print(
        f"Database '{destination}' created with 10 patients, "
        "10 addresses, and 20 visits."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
