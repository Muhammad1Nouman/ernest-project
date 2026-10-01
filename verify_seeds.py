"""Inspect the sample database without exposing sensitive values by default."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().with_name("sqltojson.db")
TABLES = ("patient", "patient_address", "patient_visit")


def _redact_patient(row: dict[str, object]) -> dict[str, object]:
    if row.get("ssn"):
        digits = "".join(character for character in str(row["ssn"]) if character.isdigit())
        row["ssn"] = f"***-**-{digits[-4:]}" if len(digits) >= 4 else "REDACTED"
    return row


def display_db_contents(
    db_path: str | Path = DEFAULT_DB_PATH, *, show_data: bool = False
) -> None:
    database = Path(db_path).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database}")

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON;")

        for table in TABLES:
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {count} rows")
            if show_data:
                rows = [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT * FROM {table} ORDER BY 1"
                    )
                ]
                if table == "patient":
                    rows = [_redact_patient(row) for row in rows]
                print(json.dumps(rows, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--show-data",
        action="store_true",
        help="Print rows with SSNs masked; the default prints counts only.",
    )
    args = parser.parse_args(argv)
    try:
        display_db_contents(args.db, show_data=args.show_data)
    except (OSError, sqlite3.Error) as error:
        parser.exit(1, f"Database verification failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
