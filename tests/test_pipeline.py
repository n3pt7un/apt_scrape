import asyncio
import pytest
from apt_scrape.pipeline import Pipeline, Stage


class CollectorStage(Stage):
    """Test stage that collects items."""
    def __init__(self):
        super().__init__("collector")
        self.items = []

    async def process(self, item):
        self.items.append(item)
        return item


class DoubleStage(Stage):
    """Test stage that doubles numeric items."""
    def __init__(self):
        super().__init__("doubler")

    async def process(self, item):
        return item * 2


class FilterStage(Stage):
    """Test stage that filters out items < 5."""
    def __init__(self):
        super().__init__("filter")

    async def process(self, item):
        if item >= 5:
            return item
        return None  # Drop item


@pytest.mark.asyncio
async def test_pipeline_single_stage():
    collector = CollectorStage()
    pipeline = Pipeline([collector])
    await pipeline.push(1)
    await pipeline.push(2)
    await pipeline.finish()
    assert collector.items == [1, 2]


@pytest.mark.asyncio
async def test_pipeline_two_stages():
    doubler = DoubleStage()
    collector = CollectorStage()
    pipeline = Pipeline([doubler, collector])
    await pipeline.push(3)
    await pipeline.push(5)
    await pipeline.finish()
    assert collector.items == [6, 10]


@pytest.mark.asyncio
async def test_pipeline_filter_drops_items():
    filter_s = FilterStage()
    collector = CollectorStage()
    pipeline = Pipeline([filter_s, collector])
    await pipeline.push(3)
    await pipeline.push(7)
    await pipeline.push(1)
    await pipeline.finish()
    assert collector.items == [7]


@pytest.mark.asyncio
async def test_pipeline_counts():
    collector = CollectorStage()
    pipeline = Pipeline([collector])
    await pipeline.push("a")
    await pipeline.push("b")
    await pipeline.push("c")
    await pipeline.finish()
    stats = pipeline.stats()
    assert stats["collector"]["processed"] == 3
