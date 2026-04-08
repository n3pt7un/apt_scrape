"""apt_scrape.stages — Concrete pipeline stages for the scraping workflow.

Stages:
    DedupStage      — Drop listings already seen (by URL)
    EnrichStage     — Fetch detail pages and merge into listing dicts
    AnalyseStage    — Score listings with LLM
    NotionPushStage — Push listings to Notion databases
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from apt_scrape.pipeline import Stage

if TYPE_CHECKING:
    from apt_scrape.browser import Fetcher
    from apt_scrape.sites.base import SiteAdapter

logger = logging.getLogger(__name__)


class DedupStage(Stage):
    """Drop duplicate listings by URL."""

    def __init__(self) -> None:
        super().__init__("dedup")
        self._seen: set[str] = set()
        self._dupe_count = 0

    @property
    def unique_count(self) -> int:
        return len(self._seen)

    @property
    def dupe_count(self) -> int:
        return self._dupe_count

    async def process(self, item: dict[str, Any]) -> dict[str, Any] | None:
        url = str(item.get("url", "")).strip()
        if not url:
            return item  # Can't dedup without URL, pass through
        if url in self._seen:
            self._dupe_count += 1
            return None
        self._seen.add(url)
        return item


class EnrichStage(Stage):
    """Fetch detail page and merge into listing dict."""

    def __init__(self, fetcher: "Fetcher", fallback_adapter: "SiteAdapter") -> None:
        super().__init__("enrich")
        self._fetcher = fetcher
        self._fallback_adapter = fallback_adapter

    async def process(self, item: dict[str, Any]) -> dict[str, Any] | None:
        from apt_scrape.sites import adapter_for_url

        url = str(item.get("url", "")).strip()
        if not url:
            return item

        adapter = adapter_for_url(url) or self._fallback_adapter
        try:
            html = await self._fetcher.fetch_with_retry(
                url,
                wait_selector=adapter.config.detail_wait_selector,
                wait_timeout=adapter.config.search_wait_timeout / 1000,
                rejection_checker=adapter.detect_rejection,
            )
            detail = adapter.parse_detail(html, url).to_dict()
            item["detail"] = detail
            item["post_date"] = detail.get("post_date", "") or item.get("post_date", "")
            item["detail_description"] = detail.get("description", "")
            item["detail_address"] = detail.get("address", "")
            item["detail_features"] = detail.get("extra_info", detail.get("features", {}))
            item["detail_costs"] = detail.get("costs", {})
            item["detail_energy_class"] = detail.get("energy_class", "")
            item["detail_agency"] = detail.get("agency", "")
        except Exception as exc:
            logger.warning("Enrich failed for %s: %s", url, exc)
        return item


class AnalyseStage(Stage):
    """Score listings with LLM analysis."""

    def __init__(self, preferences: str, concurrency: int = 5) -> None:
        super().__init__("analyse")
        self._preferences = preferences
        self._semaphore = asyncio.Semaphore(concurrency)
        self._tokens_used = 0
        self._items_analysed = 0

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    @property
    def items_analysed(self) -> int:
        return self._items_analysed

    def estimated_cost_usd(self, model: str | None = None) -> float:
        """Estimate cost based on token count and model."""
        import os
        from apt_scrape.analysis import _model_cost_per_1m_tokens
        m = model or os.environ.get("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite-preview")
        return round((self._tokens_used / 1_000_000) * _model_cost_per_1m_tokens(m), 6)

    async def process(self, item: dict[str, Any]) -> dict[str, Any]:
        from apt_scrape.analysis import _get_graph, NotionApartmentFields, score_to_stars

        async with self._semaphore:
            try:
                graph = _get_graph()
                output = await graph.ainvoke(
                    {"listing": item, "preferences": self._preferences, "result": None}
                )
                result: NotionApartmentFields = output["result"]
                item["notion_fields"] = result.model_dump()
                item["ai_score"] = result.ai_score
                item["ai_stars"] = score_to_stars(result.ai_score)
                item["ai_verdict"] = result.ai_verdict
                item["ai_reason"] = result.ai_reason
                self._tokens_used += 1000  # ~800 input + ~200 output estimate
                self._items_analysed += 1
            except Exception as exc:
                logger.warning("Analysis failed for %s: %s", item.get("url", "?"), exc)
                item["ai_score"] = 0
                item["ai_verdict"] = "Error"
                item["ai_reason"] = str(exc)
        return item


class NotionPushStage(Stage):
    """Push listings to Notion databases."""

    def __init__(self) -> None:
        super().__init__("notion_push")

    async def process(self, item: dict[str, Any]) -> dict[str, Any]:
        from apt_scrape.notion_push import push_listings
        try:
            await push_listings([item])
        except Exception as exc:
            logger.warning("Notion push failed for %s: %s", item.get("url", "?"), exc)
        return item
