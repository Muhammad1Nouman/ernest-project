"""Offline agentic ETL tests; no Gemini calls or API key required."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from typing import Any

from project.agentic_etl.agent_transformer import AIAgentTransformer
from project.agentic_etl.pipeline import run_agentic_etl
from sqlite_seed import seed_database


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def generate(
        self, prompt: str, *, user_id: str, session_id: str
    ) -> dict[str, Any]:
        del user_id, session_id
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            payload_text = prompt.split("<INPUT_JSON>", 1)[1].split(
                "</INPUT_JSON>", 1
            )[0]
            payload = json.loads(payload_text)
            patient = payload["patient"]
            address = payload["address"]
            visits = payload["visits"]
            name_parts = [
                patient.get("first_name"),
                patient.get("middle_name"),
                patient.get("last_name"),
                patient.get("suffix"),
            ]
            return {
                "patient_id": patient["patient_id"],
                "full_name": " ".join(part.title() for part in name_parts if part),
                "mrn": patient["mrn"],
                "dob": patient["dob"].split(" ", 1)[0],
                "gender": "Female" if patient["sex"] == "F" else "Male",
                "is_active": bool(patient["active"]),
                "address": {
                    "address_id": address["address_id"],
                    "street_address": " ".join(
                        part
                        for part in (
                            address["address_line1"],
                            address["address_line2"],
                        )
                        if part
                    ),
                    "city": address["city"],
                    "state": address["state"],
                    "zip_code": address["zip_code"],
                },
                "visits": [
                    {
                        "patient_visit_id": visit["patient_visit_id"],
                        "visit_date": visit["visit_date"].split(" ", 1)[0],
                    }
                    for visit in visits
                ],
            }
        finally:
            self.active -= 1


class AgenticETLTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        logging.shutdown()
        self.temporary_directory.cleanup()

    async def test_transformer_bounds_concurrency_and_preserves_order(self) -> None:
        runtime = FakeAgentRuntime()
        transformer = AIAgentTransformer(
            runtime=runtime, concurrency_limit=2, max_attempts=1
        )
        payloads = [
            {
                "patient": {
                    "patient_id": patient_id,
                    "mrn": f"MRN-{patient_id}",
                    "first_name": "JANE",
                    "middle_name": None,
                    "last_name": "DOE",
                    "suffix": None,
                    "dob": "2000-01-01 00:00:00",
                    "sex": "F",
                    "active": 1,
                    "ssn": "111-22-3333",
                },
                "address": {
                    "address_id": patient_id,
                    "address_line1": "1 Main St",
                    "address_line2": "",
                    "city": "Boston",
                    "state": "MA",
                    "zip_code": "02110",
                },
                "visits": [],
            }
            for patient_id in range(1, 6)
        ]

        results = await transformer.transform_batch_async(payloads)

        self.assertEqual([result["patient_id"] for result in results], list(range(1, 6)))
        self.assertEqual(runtime.max_active, 2)
        prompts = [transformer._build_prompt(payload) for payload in payloads]
        self.assertTrue(all("111-22-3333" not in prompt for prompt in prompts))

    async def test_agentic_etl_runs_offline_with_fake_runtime(self) -> None:
        database = seed_database(self.root / "patients.db")
        output = self.root / "agentic-output.json"
        transformer = AIAgentTransformer(
            runtime=FakeAgentRuntime(), concurrency_limit=3, max_attempts=1
        )

        count = await run_agentic_etl(
            database,
            output,
            batch_size=4,
            transformer=transformer,
        )

        records = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(count, 10)
        self.assertEqual(len(records), 10)
        self.assertEqual(records[0]["full_name"], "Maria Elena Alvarez")
        self.assertEqual(records[0]["dob"], "1978-04-12")
        self.assertEqual(records[0]["gender"], "Female")
        self.assertEqual(len(records[0]["visits"]), 2)


if __name__ == "__main__":
    unittest.main()
