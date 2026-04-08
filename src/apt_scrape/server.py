"""apt_scrape.server — MCP server for scraping Italian real estate listings.

Thin server layer: defines MCP tools and delegates to site adapters.
Each site (Immobiliare.it, Casa.it, …) is a self-contained plugin in
``apt_scrape/sites/``.

Environment variables (all optional):
    IPROYAL_HOST, IPROYAL_PORT, IPROYAL_USER, IPROYAL_PASS: IPRoyal proxy.
    BROWSER_HEADLESS: "true" (default) or "false" to show the browser window.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apt_scrape.browser import Fetcher
from apt_scrape.enrichment import enrich_post_dates, enrich_with_details
from apt_scrape.export import listings_to_csv, listings_to_markdown_table
from apt_scrape.proxy import create_proxy_provider
from apt_scrape.sites import (
    SearchFilters,
    adapter_for_url,
    get_adapter,
    list_adapter_details,
    list_adapters,
)

# ---------------------------------------------------------------------------
# Logging (stderr only — stdout is the MCP stdio transport)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("apt_scrape.server")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MAX_PAGES = 1
MAX_PAGES_LIMIT = 10
DETAIL_CONCURRENCY = int(os.getenv("DETAIL_CONCURRENCY", "5"))
VPN_ROTATE_EVERY_BATCHES = int(os.getenv("VPN_ROTATE_EVERY_BATCHES", "3"))


# ---------------------------------------------------------------------------
# Fetcher singleton (nodriver-based)
# ---------------------------------------------------------------------------
_proxy = create_proxy_provider()
# DataDome detects headless=True — default to False (shows browser window).
# On Linux servers, use BROWSER_HEADLESS=virtual for Xvfb-based headless.
_headless_raw = os.getenv("BROWSER_HEADLESS", "false").lower()
if _headless_raw == "virtual":
    _headless: bool | str = "virtual"
else:
    _headless = _headless_raw not in ("0", "false", "no")
fetcher = Fetcher(proxy_provider=_proxy, headless=_headless)


# ---------------------------------------------------------------------------
# Tool input models
# ---------------------------------------------------------------------------

_site_ids = list_adapters()


class SearchListingsInput(BaseModel):
    """Validated input for the ``rental_search_listings`` MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    city: str = Field(
        ...,
        description="City slug (e.g. 'milano', 'bologna', 'roma', 'torino')",
        min_length=1,
        max_length=100,
    )
    area: str | None = Field(
        default=None,
        description="Optional area slug inside city (e.g. 'precotto', 'turro')",
        min_length=1,
        max_length=100,
    )
    operation: str = Field(
        default="affitto",
        description="Contract type: 'affitto' (rent) or 'vendita' (sale)",
    )
    property_type: str = Field(
        default="case",
        description=(
            "Property category: case, appartamenti, attici, "
            "case-indipendenti, loft, rustici, ville, villette"
        ),
    )
    min_price: int | None = Field(default=None, description="Minimum price in EUR", ge=0)
    max_price: int | None = Field(default=None, description="Maximum price in EUR", ge=0)
    min_sqm: int | None = Field(
        default=None, description="Minimum surface in square meters", ge=0
    )
    max_sqm: int | None = Field(
        default=None, description="Maximum surface in square meters", ge=0
    )
    min_rooms: int | None = Field(
        default=None, description="Minimum number of rooms (locali)", ge=1, le=10
    )
    max_rooms: int | None = Field(
        default=None, description="Maximum number of rooms (locali)", ge=1, le=10
    )
    published_within: str | None = Field(
        default=None,
        description="Recency filter in days: '1' (today), '3', '7', '14', '30'",
        pattern=r"^(1|3|7|14|30)$",
    )
    sort: str = Field(
        default="rilevanza",
        description="Sort order (e.g. 'rilevanza', 'piu-recenti')",
    )
    source: str = Field(
        default=_site_ids[0] if _site_ids else "immobiliare",
        description=f"Site to scrape: {', '.join(_site_ids)}",
    )
    max_pages: int = Field(
        default=DEFAULT_MAX_PAGES,
        description="Number of result pages to scrape (1-10)",
        ge=1,
        le=MAX_PAGES_LIMIT,
    )
    start_page: int = Field(
        default=1,
        description="First result page to scrape (1-based)",
        ge=1,
        le=MAX_PAGES_LIMIT,
    )
    end_page: int | None = Field(
        default=None,
        description=(
            "Last result page to scrape (inclusive, 1-10). "
            "If provided, it overrides max_pages."
        ),
        ge=1,
        le=MAX_PAGES_LIMIT,
    )
    include_details: bool = Field(
        default=False,
        description=(
            "If true, fetch each listing URL and enrich output with full detail "
            "fields (description, features, costs, etc.)"
        ),
    )
    detail_limit: int | None = Field(
        default=None,
        description=(
            "Maximum number of listing detail pages to fetch when "
            "include_details=true. Default: all listings."
        ),
        ge=1,
    )
    include_csv: bool = Field(
        default=False,
        description="If true, include CSV export in response under 'csv'",
    )
    include_table: bool = Field(
        default=False,
        description="If true, include markdown table export in response under 'table'",
    )
    table_max_rows: int = Field(
        default=20,
        description="Maximum number of rows in markdown table preview",
        ge=1,
        le=200,
    )
    detail_concurrency: int = Field(
        default=DETAIL_CONCURRENCY,
        description="Parallel detail page fetches per batch (default: DETAIL_CONCURRENCY env var or 5)",
        ge=1,
        le=20,
    )
    vpn_rotate_batches: int = Field(
        default=VPN_ROTATE_EVERY_BATCHES,
        description="Rotate VPN every N batches of detail fetches (default: VPN_ROTATE_EVERY_BATCHES env var or 3)",
        ge=1,
    )

    @field_validator("city")
    @classmethod
    def normalize_city(cls, v: str) -> str:
        """Normalize city to a lowercase hyphenated slug."""
        return v.lower().strip().replace(" ", "-")

    @field_validator("area")
    @classmethod
    def normalize_area(cls, v: str | None) -> str | None:
        """Normalize area to a lowercase hyphenated slug."""
        if v is None:
            return None
        return v.lower().strip().replace(" ", "-")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Verify that *source* is a registered adapter ID."""
        available = list_adapters()
        if v not in available:
            raise ValueError(
                f"Unknown source '{v}'. Available: {', '.join(available)}"
            )
        return v


class GetListingDetailInput(BaseModel):
    """Validated input for the ``rental_get_listing_detail`` MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(
        ...,
        description="Full URL of the listing page (from search results)",
        min_length=10,
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Require *url* to start with ``http``."""
        if not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v


class DumpPageInput(BaseModel):
    """Validated input for the ``rental_dump_page`` MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(..., description="URL to fetch and dump", min_length=10)
    wait_selector: str | None = Field(
        default=None,
        description="CSS selector to wait for before capturing HTML",
    )


# ---------------------------------------------------------------------------
# MCP Server & Tools
# ---------------------------------------------------------------------------

mcp = FastMCP("rental_scraper_mcp")


@mcp.tool(
    name="rental_search_listings",
    annotations={
        "title": "Search Real Estate Listings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_listings(params: SearchListingsInput) -> str:
    """Search for rental or sale property listings.

    Builds a search URL from *params*, fetches result pages via a stealth
    browser (nodriver), and parses listing cards into structured JSON.

    Args:
        params: Validated search parameters.

    Returns:
        JSON string with ``count``, ``source``, ``search_url``, and
        ``listings`` array. Each listing contains title, price, sqm, rooms,
        bathrooms, address, url, thumbnail, description_snippet,
        raw_features, and source.
    """
    adapter = get_adapter(params.source)
    all_listings: list[dict[str, Any]] = []
    pages_scraped = 0

    if params.end_page is not None:
        start_page = params.start_page
        end_page = params.end_page
    else:
        start_page = params.start_page
        end_page = params.start_page + params.max_pages - 1

    if end_page > MAX_PAGES_LIMIT:
        return _json(
            {
                "error": (
                    f"Requested end_page={end_page} exceeds "
                    f"MAX_PAGES_LIMIT={MAX_PAGES_LIMIT}"
                )
            }
        )

    if end_page < start_page:
        return _json(
            {
                "error": "Invalid page range: end_page must be >= start_page",
                "start_page": start_page,
                "end_page": end_page,
            }
        )

    for page_num in range(start_page, end_page + 1):
        filters = SearchFilters(
            city=params.city,
            area=params.area,
            operation=params.operation,
            property_type=params.property_type,
            min_price=params.min_price,
            max_price=params.max_price,
            min_sqm=params.min_sqm,
            max_sqm=params.max_sqm,
            min_rooms=params.min_rooms,
            max_rooms=params.max_rooms,
            published_within=params.published_within,
            sort=params.sort,
            page=page_num,
        )
        url = adapter.build_search_url(filters)

        try:
            html = await fetcher.fetch_with_retry(
                url, wait_selector=adapter.config.search_wait_selector
            )
        except Exception as exc:
            return _json({"error": f"Failed to fetch page {page_num}: {exc}", "url": url})

        page_listings = adapter.parse_search(html)
        pages_scraped = page_num

        if not page_listings:
            logger.info("No more listings on page %d, stopping.", page_num)
            break

        all_listings.extend([ls.to_dict() for ls in page_listings])
        logger.info("Page %d: %d listings", page_num, len(page_listings))

    ref = SearchFilters(
        city=params.city,
        area=params.area,
        operation=params.operation,
        property_type=params.property_type,
        min_price=params.min_price,
        max_price=params.max_price,
        min_sqm=params.min_sqm,
        max_sqm=params.max_sqm,
        min_rooms=params.min_rooms,
        max_rooms=params.max_rooms,
        published_within=params.published_within,
        sort=params.sort,
        page=start_page,
    )

    detail_enriched = 0
    detail_errors: list[dict[str, str]] = []
    post_date_enriched = 0
    post_date_errors: list[dict[str, str]] = []

    if params.include_details and all_listings:
        detail_enriched, detail_errors = await enrich_with_details(
            all_listings, fetcher, adapter, params.detail_limit,
            concurrency=params.detail_concurrency,
            rotate_every_batches=params.vpn_rotate_batches,
        )

    post_date_enriched, post_date_errors = await enrich_post_dates(
        all_listings, fetcher, adapter,
        concurrency=params.detail_concurrency,
        rotate_every_batches=params.vpn_rotate_batches,
    )

    return _json(
        {
            "count": len(all_listings),
            "source": adapter.config.display_name,
            "search_url": adapter.build_search_url(ref),
            "city": params.city,
            "area": params.area,
            "pages_scraped": pages_scraped,
            "start_page": start_page,
            "end_page": end_page,
            "details_requested": params.include_details,
            "details_enriched": detail_enriched,
            "detail_errors": detail_errors,
            "post_date_enriched": post_date_enriched,
            "post_date_errors": post_date_errors,
            "csv": listings_to_csv(all_listings) if params.include_csv else "",
            "table": listings_to_markdown_table(all_listings, params.table_max_rows)
            if params.include_table
            else "",
            "listings": all_listings,
        }
    )


@mcp.tool(
    name="rental_get_listing_detail",
    annotations={
        "title": "Get Full Listing Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_listing_detail(params: GetListingDetailInput) -> str:
    """Fetch full details of a single property listing.

    Auto-detects the site from the URL and uses the matching adapter to
    extract title, price, full description, features, photos, energy class,
    agency info, costs, and address.

    Args:
        params: Input containing the listing ``url``.

    Returns:
        JSON string of the ``ListingDetail`` dict.
    """
    url = params.url
    adapter = adapter_for_url(url)

    if adapter is None:
        available = list_adapter_details()
        return _json(
            {"error": f"No adapter found for URL: {url}", "supported_sites": available}
        )

    try:
        html = await fetcher.fetch_with_retry(
            url, wait_selector=adapter.config.detail_wait_selector
        )
    except Exception as exc:
        return _json({"error": f"Failed to fetch listing: {exc}", "url": url})

    detail = adapter.parse_detail(html, url)
    return _json(detail.to_dict())


@mcp.tool(
    name="rental_list_sites",
    annotations={
        "title": "List Supported Real Estate Sites",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def list_sites() -> str:
    """List all registered real estate site adapters.

    Returns:
        JSON array of ``{site_id, display_name, base_url}`` objects.
    """
    return _json(list_adapter_details())


@mcp.tool(
    name="rental_dump_page",
    annotations={
        "title": "Dump Raw HTML of a Page (Debug)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dump_page(params: DumpPageInput) -> str:
    """Fetch a page and return raw HTML for debugging selectors.

    Captures HTML after JavaScript rendering via nodriver.

    Args:
        params: Input with ``url`` and optional ``wait_selector``.

    Returns:
        Raw HTML string (not JSON).
    """
    try:
        return await fetcher.fetch_with_retry(params.url, wait_selector=params.wait_selector)
    except Exception as exc:
        return _json({"error": str(exc), "url": params.url})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(obj: Any) -> str:
    """Serialize *obj* to a compact, human-readable JSON string."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sites = list_adapter_details()
    logger.info(
        "Starting rental_scraper_mcp with %d site(s): %s",
        len(sites),
        ", ".join(s["display_name"] for s in sites),
    )
    mcp.run()
