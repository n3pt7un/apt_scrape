"""apt_scrape.pipeline — Streaming pipeline with asyncio.Queue-connected stages."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_SENTINEL = object()  # Signals end-of-stream


@dataclass
class StageStats:
    processed: int = 0
    dropped: int = 0
    errors: int = 0
    elapsed_sec: float = 0.0


class Stage(ABC):
    """Base class for a pipeline stage."""

    def __init__(self, name: str, queue_size: int = 100) -> None:
        self.name = name
        self._in_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._out_queue: asyncio.Queue | None = None
        self._stats = StageStats()
        self._task: asyncio.Task | None = None

    @abstractmethod
    async def process(self, item: Any) -> Any | None:
        """Process one item. Return None to drop it from the pipeline."""

    async def _run(self) -> None:
        """Main loop: consume from input queue, process, push to output."""
        t0 = time.monotonic()
        while True:
            item = await self._in_queue.get()
            if item is _SENTINEL:
                if self._out_queue is not None:
                    await self._out_queue.put(_SENTINEL)
                self._in_queue.task_done()
                break
            try:
                result = await self.process(item)
                self._stats.processed += 1
                if result is not None and self._out_queue is not None:
                    await self._out_queue.put(result)
                elif result is None:
                    self._stats.dropped += 1
            except Exception as exc:
                self._stats.errors += 1
                logger.warning("Stage '%s' error: %s", self.name, exc)
            finally:
                self._in_queue.task_done()
        self._stats.elapsed_sec = time.monotonic() - t0

    def start(self) -> None:
        """Start the stage's background task."""
        self._task = asyncio.create_task(self._run(), name=f"stage-{self.name}")

    async def stop(self) -> None:
        """Wait for the stage to finish."""
        if self._task:
            await self._task


class Pipeline:
    """Chain of Stages connected by asyncio.Queue."""

    def __init__(self, stages: list[Stage]) -> None:
        self._stages = stages
        for i in range(len(stages) - 1):
            stages[i]._out_queue = stages[i + 1]._in_queue
        for stage in stages:
            stage.start()

    async def push(self, item: Any) -> None:
        """Push an item into the first stage."""
        await self._stages[0]._in_queue.put(item)

    async def finish(self) -> None:
        """Signal end-of-stream and wait for all stages to complete."""
        await self._stages[0]._in_queue.put(_SENTINEL)
        for stage in self._stages:
            await stage.stop()

    def stats(self) -> dict[str, dict[str, Any]]:
        """Return processing statistics for each stage."""
        return {
            stage.name: {
                "processed": stage._stats.processed,
                "dropped": stage._stats.dropped,
                "errors": stage._stats.errors,
                "elapsed_sec": round(stage._stats.elapsed_sec, 2),
            }
            for stage in self._stages
        }
