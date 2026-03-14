"""Tests for apt_scrape.notion_push — Notion Apartments DB ingestion."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


LISTING = {
    "title": "Bilocale luminoso",
    "url": "https://www.immobiliare.it/annunci/12345/",
    "price": "€ 900/mese",
    "sqm": "55 m²",
    "rooms": "2 locali",
    "address": "Milano, Bicocca",
    "source": "Immobiliare.it",
    "detail": {
        "title": "Bilocale luminoso con balcone",
        "size": "55 m²",
        "floor": "3",
    },
    "detail_address": "Via Tal dei Tali 10, Bicocca, Milano",
    "detail_agency": "Agenzia Rossi",
    "detail_energy_class": "C",
    "notion_fields": {
        "title": "Bilocale luminoso con balcone",
        "rent_per_month": 900.0,
        "size_sqm": 55.0,
        "rooms": "2 locali",
        "floor": "3",
        "address": "Via Tal dei Tali 10, Bicocca, Milano, MI",
        "energy_class": "C",
        "furnished": False,
        "available_from": None,
        "ai_score": 72,
        "ai_verdict": "Good match",
        "ai_reason": "Has balcony and good size.",
        "notes": None,
    },
    "ai_score": 72,
    "ai_stars": "⭐⭐⭐⭐",
    "ai_verdict": "Good match",
    "ai_reason": "Has balcony and good size.",
    "_area": "bicocca",
    "_city": "milano",
}


def test_parse_price_numeric():
    """_parse_price_numeric() extracts the first integer from a price string."""
    from apt_scrape.notion_push import _parse_price_numeric

    assert _parse_price_numeric("€ 1.200/mese") == 1200.0
    assert _parse_price_numeric("900 €/mese") == 900.0
    assert _parse_price_numeric("€ 1,500") == 1500.0
    assert _parse_price_numeric("non disponibile") is None
    assert _parse_price_numeric("") is None


def test_parse_sqm_numeric():
    """_parse_sqm_numeric() extracts the numeric size from a sqm string."""
    from apt_scrape.notion_push import _parse_sqm_numeric

    assert _parse_sqm_numeric("65 m²") == 65.0
    assert _parse_sqm_numeric("120m²") == 120.0
    assert _parse_sqm_numeric("n.d.") is None
    assert _parse_sqm_numeric("") is None


def test_deslugify_area():
    """_deslugify_area() converts a hyphenated slug to a title-cased string."""
    from apt_scrape.notion_push import _deslugify_area

    assert _deslugify_area("bicocca") == "Bicocca"
    assert _deslugify_area("porta-venezia") == "Porta Venezia"
    assert _deslugify_area("niguarda-ca-granda") == "Niguarda Ca Granda"


def test_score_to_stars():
    """_score_to_stars() maps 0–100 integers to emoji strings."""
    from apt_scrape.notion_push import _score_to_stars

    assert _score_to_stars(0) == "⭐"
    assert _score_to_stars(39) == "⭐⭐"
    assert _score_to_stars(40) == "⭐⭐⭐"
    assert _score_to_stars(79) == "⭐⭐⭐⭐"
    assert _score_to_stars(80) == "⭐⭐⭐⭐⭐"


def test_build_properties_uses_notion_fields():
    """_build_properties() prefers notion_fields values over raw listing fields."""
    from apt_scrape.notion_push import _build_properties

    props = _build_properties(LISTING, area_page_id=None, agency_page_id=None)
    # title from notion_fields
    assert props["Apartment"]["title"][0]["text"]["content"] == "Bilocale luminoso con balcone"
    # numeric rent from notion_fields
    assert props["Rent (€/mo)"]["number"] == 900.0
    # energy class from notion_fields (single letter)
    assert props["Energy Class"]["select"]["name"] == "C"
    # furnished checkbox from notion_fields
    assert props["Furnished"]["checkbox"] is False
    # AI score and star rating
    assert props["AI Score"]["number"] == 72
    assert props["Score"]["select"]["name"] == "⭐⭐⭐⭐"


def test_build_properties_sets_place_when_lat_lon_provided():
    """_build_properties() writes Place property when lat_lon is given."""
    from apt_scrape.notion_push import _build_properties

    props = _build_properties(LISTING, None, None, lat_lon=(45.4654, 9.1859))
    assert props["Place"] == {"place": {"lat": 45.4654, "lon": 9.1859}}


def test_build_properties_no_place_without_lat_lon():
    """_build_properties() omits Place when lat_lon is None."""
    from apt_scrape.notion_push import _build_properties

    props = _build_properties(LISTING, None, None, lat_lon=None)
    assert "Place" not in props


@pytest.mark.asyncio
async def test_push_listings_creates_page_for_new_listing():
    """push_listings() creates a Notion page when listing URL is not already in DB."""
    from apt_scrape.notion_push import push_listings

    with patch("apt_scrape.notion_push.AsyncClient") as MockClient, \
         patch("apt_scrape.notion_push._geocode_address", new=AsyncMock(return_value=(45.4654, 9.1859))):
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        # _ensure_schema: retrieve returns empty properties dict
        client.databases.retrieve = AsyncMock(return_value={"properties": {}})
        client.databases.update = AsyncMock(return_value={})
        # Dedup: new listing; area match found; agency match found
        client.databases.query = AsyncMock(side_effect=[
            {"results": []},                         # dedup: no existing page
            {"results": [{"id": "area-page-id"}]},   # area lookup
            {"results": [{"id": "agency-page-id"}]}, # agency lookup
        ])
        client.pages.create = AsyncMock(return_value={
            "id": "new-page-id",
            "url": "https://www.notion.so/new-page-id",
        })

        listings = [dict(LISTING)]
        await push_listings(listings)

    assert listings[0]["notion_page_id"] == "new-page-id"
    assert listings[0]["notion_skipped"] is False
    client.pages.create.assert_called_once()
    # Verify Place was included in the page properties
    call_kwargs = client.pages.create.call_args[1]
    assert call_kwargs["properties"]["Place"] == {"place": {"lat": 45.4654, "lon": 9.1859}}


@pytest.mark.asyncio
async def test_push_listings_skips_duplicate():
    """push_listings() skips a listing whose URL already exists in Notion."""
    from apt_scrape.notion_push import push_listings

    with patch("apt_scrape.notion_push.AsyncClient") as MockClient:
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        client.databases.retrieve = AsyncMock(return_value={"properties": {}})
        client.databases.update = AsyncMock(return_value={})
        # Dedup query returns an existing page
        client.databases.query = AsyncMock(return_value={
            "results": [{"id": "existing-id", "url": "https://www.notion.so/existing-id"}]
        })

        listings = [dict(LISTING)]
        await push_listings(listings)

    assert listings[0]["notion_skipped"] is True
    assert listings[0].get("notion_page_id") == "existing-id"


@pytest.mark.asyncio
async def test_push_listings_creates_agency_when_missing():
    """push_listings() creates a new Agency page when agency is not found."""
    from unittest.mock import patch as _patch
    import os
    from apt_scrape.notion_push import push_listings

    env_overrides = {
        "NOTION_API_KEY": "test-key",
        "NOTION_APARTMENTS_DB_ID": "apt-db-id",
        "NOTION_AREAS_DB_ID": "areas-db-id",
        "NOTION_AGENCIES_DB_ID": "agencies-db-id",
    }
    with patch("apt_scrape.notion_push.AsyncClient") as MockClient, \
         patch("apt_scrape.notion_push._geocode_address", new=AsyncMock(return_value=None)), \
         _patch.dict(os.environ, env_overrides):
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        client.databases.retrieve = AsyncMock(return_value={"properties": {}})
        client.databases.update = AsyncMock(return_value={})
        # Dedup: new listing; area: no match; agency: no match
        client.databases.query = AsyncMock(side_effect=[
            {"results": []},   # dedup
            {"results": []},   # area lookup (no match)
            {"results": []},   # agency lookup (no match)
        ])
        client.pages.create = AsyncMock(side_effect=[
            {"id": "new-agency-id", "url": "https://www.notion.so/new-agency-id"},  # agency
            {"id": "new-apt-id", "url": "https://www.notion.so/new-apt-id"},         # apartment
        ])

        listings = [dict(LISTING)]
        await push_listings(listings)

    # Two pages created: agency first, then apartment
    assert client.pages.create.call_count == 2
