# SQL-to-JSON ETL Solutions and Privacy Engineering Overview

## Purpose

This repository contains two implementations of the same synthetic patient
SQL-to-JSON workflow:

1. **Deterministic ETL** — a conventional, standard-library Python pipeline.
2. **Agentic ETL** — a Google Agent Development Kit (ADK) pipeline using a
   Gemini model for structured normalization, followed by strict local
   validation.

Both solutions demonstrate privacy-conscious engineering practices suitable
for a presales prototype. They are not, by themselves, a declaration or
certification that a production deployment is HIPAA compliant. HIPAA
compliance depends on the complete technical environment, organizational
policies, operating procedures, contracts, workforce practices, and documented
risk-management program.

The correct acronym is **HIPAA**: Health Insurance Portability and
Accountability Act.

## Solution 1: Deterministic ETL

### What it does

The deterministic implementation reads relational patient, address, and visit
records from SQLite and exports nested JSON using predictable Python
transformations.

```text
SQLite (read-only)
    -> relationship and schema validation
    -> deterministic field normalization and SSN masking
    -> streaming JSON serialization
    -> atomic output replacement
```

### How it works

- `project/extract/extractor.py` opens SQLite in read-only mode, checks foreign
  keys, loads related records, and emits one aggregated payload per patient.
- `project/transform/schemas.py` validates required tables, fields, types, and
  relationships before transformation.
- `project/transform/transformer.py` cleans null-like values, normalizes
  booleans, constructs nested addresses and visits, and masks SSNs so only the
  final four digits remain.
- `project/load/loader.py` streams JSON through a restricted temporary file,
  flushes it to disk, and atomically replaces the destination only after the
  export succeeds.
- `project/main.py` provides configurable database, output, and log paths.

This approach is appropriate when transformations must be reproducible,
auditable, fast, inexpensive, and independent of an external model.

## Solution 2: Agentic ETL

### What it does

The agentic implementation uses a Google ADK `LlmAgent` to normalize selected
patient fields into a strict structured-output contract. Every response is
validated locally before it can be exported.

```text
SQLite (read-only)
    -> relationship validation
    -> data-minimized model payload
    -> bounded asynchronous ADK normalization
    -> strict Pydantic validation
    -> atomic JSON output replacement
```

### How it works

- `project/agentic_etl/agent.py` defines the single-turn normalization agent,
  its transformation rules, zero-temperature generation, output schema, and
  prompt-injection boundary instructions.
- `project/agentic_etl/agent_transformer.py` removes fields not needed by the
  model, manages isolated ADK sessions, bounds concurrency, applies request
  timeouts and retries, and rejects responses whose patient identifier does
  not match the input.
- `project/agentic_etl/schemas.py` defines strict Pydantic models that reject
  unknown fields and invalid dates, identifiers, enums, or values.
- `project/agentic_etl/pipeline.py` processes bounded batches while preserving
  source ordering.
- `project/agentic_etl/loader.py` streams validated responses into an atomic
  JSON output file with restricted permissions where the platform supports
  them.
- `project/main_agentic_etl.py` exposes model, batch-size, concurrency, retry,
  timeout, database, output, and log options.

Before a model request, the agentic implementation excludes full SSNs, phone
numbers, email addresses, symptoms, and prescriptions. It still sends fields
such as name, MRN, date of birth, address, and visit dates because those fields
are part of the normalization task. With real patient data, these values may be
PHI and must only be processed through an approved service and deployment
architecture.

## Comparison

| Area | Deterministic ETL | Agentic ETL |
|---|---|---|
| Transformation | Explicit Python rules | ADK agent with structured model output |
| Reproducibility | Fully deterministic | Constrained but model-dependent |
| Dependencies | Python standard library | Google ADK and Pydantic |
| Network use | None | Model service required |
| Validation | Local runtime schema checks | Local input checks plus strict Pydantic output validation |
| Sensitive-field handling | SSN is masked in exported JSON | SSN, contact, symptom, and prescription fields are not sent to the model or exported |
| Throughput controls | Streaming, one record at a time | Batching and bounded asynchronous concurrency |
| Failure handling | Fail closed before destination replacement | Timeout, retry, validation, then fail closed before replacement |
| Best fit | Stable production mappings and offline processing | Flexible normalization where model reasoning adds value |

## HIPAA-aligned privacy and security practices

The following safeguards are implemented in the current repository:

- **Synthetic development data.** The included database contains fictional
  records rather than real PHI.
- **SSN protection.** The deterministic export masks full SSNs. The agentic
  workflow excludes SSNs from model requests and its output contract.
- **Read-only extraction.** Both workflows open the source SQLite database in
  read-only mode.
- **Relationship integrity checks.** Foreign-key checks and patient/address/
  visit relationship validation reject inconsistent source data.
- **Runtime schema validation.** Records are validated before export. Agentic
  output receives an additional strict Pydantic validation pass locally.
- **Atomic output replacement.** A failed run does not replace a valid output
  with a partially written JSON document.
- **Restricted file permissions.** Temporary output files are limited to the
  current operating-system user where supported.
- **Deterministic ordering.** Source, batch, visit, and output ordering are
  preserved and covered by tests.
- **Privacy-conscious logging.** Operational logs record counts, paths,
  status, and errors without deliberately logging patient record bodies or
  model prompts.
- **Safe input failure.** Missing, unreadable, structurally invalid, or
  relationship-invalid databases fail instead of being silently created or
  partially processed.
- **Model data minimization.** The agentic workflow sends only the fields its
  normalization task requires.
- **Credential hygiene.** API credentials are read from the environment and
  are excluded from version control.

These measures support confidentiality and integrity, but they do not make the
exported deterministic data formally de-identified. Names, addresses, dates of
birth, medical record numbers, contact details, and clinical information may
still identify a person. HHS describes **Expert Determination** and **Safe
Harbor** as the two methods for treating health information as de-identified
under the HIPAA Privacy Rule. See the official [HHS de-identification
guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html).

### Console-output clarification

The agentic command prints only a completion summary and does not print patient
records. The deterministic command currently prints its generated, SSN-masked
JSON to standard output because that was an explicit requirement of the
original assignment. Therefore, the statement “patient records are no longer
printed to the console” is accurate for the agentic CLI, but not for the
deterministic CLI.

For a production deployment, invoke `run_pipeline()` as a library operation or
remove the deterministic CLI's JSON print behavior. Console capture, shell
history, CI logs, and observability systems must also be evaluated before real
PHI is processed.

## Production controls still required

A real deployment handling ePHI would require controls outside this source
repository, including:

- encryption in transit and at rest;
- authenticated, role-based, least-privilege access;
- unique user identities and appropriate session controls;
- patient-data access and disclosure audit trails;
- centralized secrets and encryption-key management;
- secured backups, disaster recovery, and tested restoration procedures;
- data classification, retention, deletion, and disposal policies;
- vulnerability management, patching, monitoring, and alerting;
- incident detection, response, breach assessment, and notification processes;
- workforce training and documented administrative procedures;
- periodic technical and organizational risk assessments;
- vendor due diligence and applicable Business Associate Agreements (BAAs);
- documented configuration and responsibility boundaries for any cloud or
  model provider; and
- legal, privacy, and security review for the intended use and jurisdiction.

HHS identifies risk analysis as foundational to selecting appropriate HIPAA
Security Rule safeguards. Its cloud guidance also states that a covered entity
or business associate using a cloud service to process ePHI must enter into an
applicable HIPAA-compliant BAA and otherwise comply with the HIPAA Rules. See
the official [HHS risk-analysis
guidance](https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis/index.html)
and [HHS cloud-computing
guidance](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html).

## Testing and verification

The repository includes automated coverage for both implementations:

- deterministic end-to-end extraction, transformation, masking, and export;
- invalid-patient and invalid-relationship rejection;
- missing-database failure without accidental database creation;
- deterministic ordering;
- agentic batching and concurrency limits;
- local structured-output validation;
- agentic field minimization, including exclusion of full SSNs; and
- an offline agent runtime so tests require no credentials, network calls, or
  model usage charges.

Run all tests from the repository root:

```powershell
python -B -m unittest discover -s tests -v
```

## Accessing both solutions

Run the deterministic ETL:

```powershell
python -m project.main
```

Install the agentic dependencies in an isolated virtual environment and run
the agentic ETL:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-agentic.txt
$env:GEMINI_API_KEY = "your-api-key"
python -m project.main_agentic_etl
```

For real PHI, do not run the agentic workflow merely by adding an API key. Use
only an approved service configuration and organization-approved controls,
contracts, data flows, and deployment environment.

## Accurate presales statement

> The application incorporates HIPAA-aligned, privacy-conscious engineering
> practices and uses synthetic data during development. Production compliance
> controls would be implemented for the target deployment environment.

Avoid statements such as “the application is HIPAA compliant” unless the
complete deployed system and operating organization have undergone the
appropriate legal, privacy, security, contractual, and risk reviews.
