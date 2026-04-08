import asyncio
import pytest
from apt_scrape.stages import DedupStage


@pytest.mark.asyncio
async def test_dedup_removes_duplicates():
    stage = DedupStage()
    results = []
    items = [
        {"url": "https://example.com/1", "title": "A"},
        {"url": "https://example.com/2", "title": "B"},
        {"url": "https://example.com/1", "title": "A duplicate"},
    ]
    for item in items:
        result = await stage.process(item)
        if result is not None:
            results.append(result)
    assert len(results) == 2
    assert results[0]["title"] == "A"
    assert results[1]["title"] == "B"


@pytest.mark.asyncio
async def test_dedup_keeps_first():
    stage = DedupStage()
    r1 = await stage.process({"url": "https://a.com/1", "title": "First"})
    r2 = await stage.process({"url": "https://a.com/1", "title": "Second"})
    assert r1 is not None
    assert r2 is None


@pytest.mark.asyncio
async def test_dedup_stats():
    stage = DedupStage()
    await stage.process({"url": "https://a.com/1"})
    await stage.process({"url": "https://a.com/1"})
    await stage.process({"url": "https://a.com/2"})
    assert stage.unique_count == 2
    assert stage.dupe_count == 1
