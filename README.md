# SQL-to-JSON ETL Pipeline

Extracts synthetic patient records from SQLite, normalizes them, and exports
them as JSON. The repository contains two implementations of the same ETL:

| Pipeline | Entry point | Transform step | Dependencies | Output |
| --- | --- | --- | --- | --- |
| **Deterministic** | `project/main.py` | Rule-based Python transformer | Standard library only | `patient_output.json` |
| **Agentic** | `project/main_agentic_etl.py` | Google ADK agent (Gemini) with strict Pydantic validation | `requirements-agentic.txt` + Gemini credentials | `patient_output_agentic.json` |

For an implementation comparison, security controls, HIPAA-aligned engineering
position, and production-readiness limitations, see
[`SOLUTION_AND_PRIVACY_OVERVIEW.md`](SOLUTION_AND_PRIVACY_OVERVIEW.md).

## Requirements

- Python 3.10 or newer
- The deterministic ETL needs no third-party packages
- The agentic ETL needs the packages in `requirements-agentic.txt`
  (`google-adk`, `pydantic`, `python-dotenv`) and a Gemini API key or Vertex AI
  credentials

## Quick start

All commands run from this directory (the one containing `sqltojson.db`).

```powershell
# Deterministic ETL (no setup needed)
python -m project.main

# Agentic ETL
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-agentic.txt
Copy-Item .env.example .env      # then put your key in .env
python -m project.main_agentic_etl
```

Both entry points can also be run by file path, for example
`python project/main_agentic_etl.py`.

## Included sample data

`sqltojson.db` contains:

- 10 synthetic patients
- 10 synthetic addresses (one per patient)
- 20 synthetic visits (two per patient)

All names, identifiers, contact details, medical details, and Social Security
numbers are fictional test data. The source database keeps the complete
synthetic records for demonstration; exported JSON masks SSNs before writing or
printing them.

## Project structure

```text
project/
├── extract/
│   └── extractor.py         # Read and aggregate SQLite records (read-only)
├── transform/
│   ├── schemas.py           # Runtime validation rules
│   └── transformer.py       # Clean and reshape records
├── load/
│   └── loader.py            # Atomically write JSON output
├── agentic_etl/
│   ├── agent.py             # Google ADK LlmAgent definition and instructions
│   ├── agent_transformer.py # Async bounded agent execution with retries
│   ├── loader.py            # Async atomic JSON streaming
│   ├── pipeline.py          # Batch orchestration
│   └── schemas.py           # Pydantic structured-output contract
├── main.py                  # Deterministic ETL CLI
└── main_agentic_etl.py      # Agentic ETL CLI
tests/
├── test_pipeline.py         # Deterministic ETL regression tests
└── test_agentic_etl.py      # Offline tests with a fake agent runtime
sqlite_seed.py               # Rebuild the synthetic sample database
verify_seeds.py              # Inspect sample table counts or redacted rows
sqltojson.db                 # Synthetic SQLite input
patient_output.json          # Example deterministic output
requirements-agentic.txt     # Agentic ETL dependencies
.env.example                 # Credential template for the agentic ETL
```

Generated at runtime (Git-ignored): `.env`, `patient_output_agentic.json`,
`project/log.txt`, `project/agentic_etl/log.txt`.

## Deterministic ETL

```powershell
python -m project.main
```

The command:

1. Reads `sqltojson.db` in read-only mode.
2. Validates and transforms patient records.
3. Prints the generated JSON to standard output.
4. Writes the same JSON to `patient_output.json`.
5. Writes runtime messages to `project/log.txt` and standard error.

| Option | Default | Description |
| --- | --- | --- |
| `--db` | `sqltojson.db` | Source SQLite database |
| `--output` | `patient_output.json` | Target JSON file |
| `--log` | `project/log.txt` | Runtime log file (appended) |

```powershell
python -m project.main --db path\input.db --output path\output.json --log path\run.log
```

## Agentic ETL (Google ADK + Gemini)

### 1. Install dependencies

Use a virtual environment. `google-adk` upgrades shared packages such as
`tenacity` and `watchdog`, which can conflict with other tools (for example
Streamlit) installed in the same interpreter.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-agentic.txt
```

### 2. Configure credentials

Copy the template and fill in one option:

```powershell
Copy-Item .env.example .env
```

**Google AI Studio** — create a key at <https://aistudio.google.com/apikey>:

```dotenv
GEMINI_API_KEY=your-api-key
```

`GOOGLE_API_KEY` is accepted as an alternative name.

**Vertex AI** — authenticate with Application Default Credentials
(`gcloud auth application-default login`) and set:

```dotenv
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
```

`.env` is loaded from this directory and is excluded from Git. Variables already
set in the environment take precedence over `.env`. Save the file before
running; the CLI reads it from disk at startup. Never reuse a key that has been
exposed in chat, logs, or source control.

### 3. Run

```powershell
python -m project.main_agentic_etl
```

Expected final line:

```text
Agentic ETL complete: exported 10 records to ...\patient_output_agentic.json
```

| Option | Default | Description |
| --- | --- | --- |
| `--db` | `sqltojson.db` | Source SQLite database |
| `--output` | `patient_output_agentic.json` | Target JSON file |
| `--log` | `project/agentic_etl/log.txt` | Runtime log file (appended) |
| `--model` | `gemini-3.5-flash-lite` | Gemini model used by the ADK agent |
| `--batch-size` | `25` | Records extracted and normalized per batch |
| `--concurrency` | `5` | Maximum simultaneous model requests |
| `--max-attempts` | `3` | Attempts per record before the run fails |
| `--timeout` | `60` | Seconds allowed per model request |

```powershell
python -m project.main_agentic_etl --model gemini-3.5-flash-lite --batch-size 25 --concurrency 5 --max-attempts 3 --timeout 60
```

### How it works

1. **Extract:** the shared `SQLiteExtractor` streams each patient with their
   address and visits.
2. **Minimize:** only the fields needed for normalization are sent to the
   model — IDs, MRN, name parts, date of birth, sex, active flag, address, and
   visit IDs and dates. SSNs, phone numbers, email addresses, symptoms, and
   prescriptions are never sent.
3. **Normalize:** a temperature-0 ADK `LlmAgent` builds `full_name`,
   converts dates to ISO-8601, maps gender to `Male`/`Female`/`Other`/`Unknown`,
   converts `active` to a boolean, and merges address lines. Record contents are
   wrapped as delimited data and treated as untrusted input.
4. **Validate:** every response is parsed with the strict
   `TransformedPatientSchema` (unknown fields rejected) and its `patient_id`
   must match the input. A failed request or validation is retried with
   exponential backoff (1 s, 2 s, 4 s, max 8 s) up to `--max-attempts`; if a
   record still fails, the whole run fails and no partial file is written.
5. **Load:** records stream in input order to a temporary file, which is
   fsynced and atomically renamed to the output path.

### Output shape

```json
{
  "patient_id": 10042,
  "full_name": "Maria Elena Alvarez",
  "mrn": "MRN-88213",
  "dob": "1978-04-12",
  "gender": "Female",
  "is_active": true,
  "address": {
    "address_id": 1,
    "street_address": "100 Main St Apt 1",
    "city": "Boston",
    "state": "MA",
    "zip_code": "02110"
  },
  "visits": [
    { "patient_visit_id": 1, "visit_date": "2026-08-15" }
  ]
}
```

### Troubleshooting

| Error | Fix |
| --- | --- |
| `Install agentic ETL dependencies with: python -m pip install -r requirements-agentic.txt` | Install the requirements into the interpreter you are running (activate `.venv` first). |
| `Set GOOGLE_API_KEY or GEMINI_API_KEY, or configure Vertex AI ...` | Add a key to `.env` in this directory and **save the file**, or set `$env:GEMINI_API_KEY` in the shell. |
| `Failed to normalize patient <id> after N attempt(s).` | Check the log for the underlying cause (invalid key, quota, timeout, schema mismatch). Raise `--timeout` or `--max-attempts`, or lower `--concurrency` for rate limits. |

Full tracebacks are written to `project/agentic_etl/log.txt`.

## Run the tests

```powershell
python -B -m unittest discover -s tests -v
```

Install `requirements-agentic.txt` before running the full suite. The agentic
tests use a fake agent runtime, so they need no credentials, make no network
calls, and incur no model charges.

## Rebuild the sample database

The seeder refuses to overwrite an existing database unless `--force` is given.
Replacement is atomic, so the existing database is preserved if seeding fails.

```powershell
python sqlite_seed.py --force
python verify_seeds.py               # row counts
python verify_seeds.py --show-data   # sample rows with SSNs masked
```

## Delivery checklist

Exclude local credentials (`.env`), virtual environments, caches, runtime logs,
and generated agent output from any deliverable. Both entry points recreate
their output and log files as needed. Recipients supply their own Gemini
credentials using `.env.example` as the template.

## Privacy and security note

The implementation uses privacy-conscious practices including read-only source
access, data minimization before model calls, schema and relationship
validation, SSN masking, deterministic ordering, bounded concurrency, atomic
file replacement, and logs that exclude patient record contents. These are
HIPAA-aligned engineering practices, but application code alone does not make a
deployment HIPAA compliant. Do not send real PHI to an external model without
an approved deployment architecture, risk analysis, access controls,
encryption, audit trails, incident response, secure backups, and all applicable
contracts and policies, including a BAA where required.
