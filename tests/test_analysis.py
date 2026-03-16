"""Tests for apt_scrape.analysis — LangGraph listing scorer."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import logging

import pytest

# Minimal listing dict (detail-enriched)
LISTING = {
    "title": "Bilocale luminoso",
    "price": "€ 900/mese",
    "sqm": "55 m²",
    "rooms": "2 locali",
    "address": "Milano, Bicocca",
    "detail": {
        "title": "Bilocale luminoso con balcone",
        "size": "55 m²",
        "floor": "3",
    },
    "detail_address": "Via Tal dei Tali 10, Bicocca, Milano",
    "detail_description": "Appartamento luminoso con balcone e vista verde.",
    "detail_features": {"Riscaldamento": "autonomo", "Piano": "3"},
    "detail_costs": {"Spese condominiali": "50€/mese"},
    "detail_energy_class": "C",
}


def test_score_to_stars():
    """score_to_stars() maps 0–100 integers to emoji strings."""
    from apt_scrape.analysis import score_to_stars

    assert score_to_stars(0) == "⭐"
    assert score_to_stars(19) == "⭐"
    assert score_to_stars(20) == "⭐⭐"
    assert score_to_stars(39) == "⭐⭐"
    assert score_to_stars(40) == "⭐⭐⭐"
    assert score_to_stars(59) == "⭐⭐⭐"
    assert score_to_stars(60) == "⭐⭐⭐⭐"
    assert score_to_stars(79) == "⭐⭐⭐⭐"
    assert score_to_stars(80) == "⭐⭐⭐⭐⭐"
    assert score_to_stars(100) == "⭐⭐⭐⭐⭐"


def test_format_listing_context_includes_key_fields():
    """_format_listing_context() returns a string containing all key fields."""
    from apt_scrape.analysis import _format_listing_context

    ctx = _format_listing_context(LISTING)
    assert "Bilocale luminoso con balcone" in ctx  # detail.title preferred
    assert "900" in ctx                             # price
    assert "55" in ctx                              # size
    assert "3 locali" in ctx or "2 locali" in ctx   # rooms
    assert "Bicocca" in ctx                          # address
    assert "luminoso con balcone" in ctx             # full description, not truncated
    assert "autonomo" in ctx                         # features
    assert "50€/mese" in ctx                         # costs
    assert "C" in ctx                                # energy class


@pytest.mark.asyncio
async def test_analyse_listings_adds_ai_fields():
    """analyse_listings() stamps ai_score, ai_stars, ai_verdict, ai_reason and notion_fields onto each listing."""
    from apt_scrape.analysis import NotionApartmentFields, analyse_listings

    fake_result = NotionApartmentFields(
        title="Bilocale luminoso con balcone",
        rent_per_month=900.0,
        size_sqm=55.0,
        rooms="2 locali",
        floor="3",
        address="Via Tal dei Tali 10, Bicocca, Milano, MI",
        energy_class="C",
        furnished=False,
        ai_score=72,
        ai_verdict="Good match",
        ai_reason="Has balcony and good size.",
    )

    # Patch the compiled LangGraph app invoke
    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.return_value = {"result": fake_result}
        mock_get_graph.return_value = mock_app

        listings = [dict(LISTING), dict(LISTING)]
        await analyse_listings(listings, preferences="I want a bright apartment.")

    for listing in listings:
        assert listing["ai_score"] == 72
        assert listing["ai_stars"] == "⭐⭐⭐⭐"
        assert listing["ai_verdict"] == "Good match"
        assert listing["ai_reason"] == "Has balcony and good size."
        nf = listing["notion_fields"]
        assert nf["title"] == "Bilocale luminoso con balcone"
        assert nf["rent_per_month"] == 900.0
        assert nf["energy_class"] == "C"
        assert nf["furnished"] is False


@pytest.mark.asyncio
async def test_analyse_listings_handles_error_gracefully():
    """analyse_listings() falls back to score=0/Error when LLM raises LLMAPIError."""
    from apt_scrape.analysis import LLMAPIError, analyse_listings

    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = LLMAPIError("network error")
        mock_get_graph.return_value = mock_app

        listings = [dict(LISTING)]
        await analyse_listings(listings, preferences="I want a bright apartment.")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    assert "network error" in listings[0]["ai_reason"]


@pytest.mark.asyncio
async def test_api_failure_logs_distinct_message(caplog):
    """_score_one() emits 'LLM API failure' warning with listing URL on API errors."""
    from apt_scrape.analysis import LLMAPIError, analyse_listings

    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = LLMAPIError("connection timeout")
        mock_get_graph.return_value = mock_app

        with caplog.at_level(logging.WARNING, logger="apt_scrape.analysis"):
            listings = [dict(LISTING)]
            listings[0]["url"] = "https://example.com/apt/1"
            await analyse_listings(listings, preferences="want bright apt")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    assert any("LLM API failure" in r.message for r in caplog.records)
    assert any("https://example.com/apt/1" in r.message for r in caplog.records)
    assert not any("parse failure" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_parse_failure_logs_distinct_message(caplog):
    """_score_one() emits 'LLM parse failure' warning with listing URL on parse errors."""
    from apt_scrape.analysis import LLMParseError, analyse_listings

    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = LLMParseError("invalid JSON")
        mock_get_graph.return_value = mock_app

        with caplog.at_level(logging.WARNING, logger="apt_scrape.analysis"):
            listings = [dict(LISTING)]
            listings[0]["url"] = "https://example.com/apt/1"
            await analyse_listings(listings, preferences="want bright apt")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    assert any("LLM parse failure" in r.message for r in caplog.records)
    assert any("https://example.com/apt/1" in r.message for r in caplog.records)
    assert not any("LLM API failure" in r.message for r in caplog.records)


def test_load_preferences_from_file(tmp_path):
    """load_preferences() reads a plain-text file and returns its content."""
    from apt_scrape.analysis import load_preferences

    prefs_file = tmp_path / "preferences.txt"
    prefs_file.write_text("I want a balcony.\nNo ground floor.", encoding="utf-8")

    content = load_preferences(str(prefs_file))
    assert "balcony" in content
    assert "ground floor" in content


def test_load_preferences_missing_file_raises():
    """load_preferences() raises FileNotFoundError for missing files."""
    from apt_scrape.analysis import load_preferences

    with pytest.raises(FileNotFoundError):
        load_preferences("/nonexistent/path/preferences.txt")
