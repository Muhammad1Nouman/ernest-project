"""Batch-oriented orchestration for the asynchronous agentic ETL."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from pathlib import Path
from typing import Any

from ..extract.extractor import SQLiteExtractor
from .agent_transformer import AIAgentTransformer
from .loader import AsyncJSONLoader


def batched(
    records: Iterator[dict[str, Any]], batch_size: int
) -> Iterator[list[dict[str, Any]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    batch: list[dict[str, Any]] = []
    for record in records:
        batch.append(record)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


async def transformed_record_stream(
    extractor: SQLiteExtractor,
    transformer: AIAgentTransformer,
    batch_size: int,
) -> AsyncIterator[Mapping[str, Any]]:
    logger = logging.getLogger(__name__)
    for batch_number, batch in enumerate(
        batched(extractor.iter_patients(), batch_size), start=1
    ):
        logger.info(
            "Normalizing agentic ETL batch %d containing %d records",
            batch_number,
            len(batch),
        )
        results = await transformer.transform_batch_async(batch)
        for result in results:
            yield result


async def run_agentic_etl(
    db_path: str | Path,
    output_path: str | Path,
    *,
    batch_size: int = 25,
    concurrency: int = 5,
    model_name: str = "gemini-3.5-flash-lite",
    max_attempts: int = 3,
    request_timeout_seconds: float = 60.0,
    transformer: AIAgentTransformer | None = None,
) -> int:
    """Extract, normalize through ADK, and stream validated JSON to disk."""
    extractor = SQLiteExtractor(db_path)
    active_transformer = transformer or AIAgentTransformer(
        model_name=model_name,
        concurrency_limit=concurrency,
        max_attempts=max_attempts,
        request_timeout_seconds=request_timeout_seconds,
    )
    loader = AsyncJSONLoader(output_path)
    records = transformed_record_stream(extractor, active_transformer, batch_size)
    return await loader.load_async(records)
