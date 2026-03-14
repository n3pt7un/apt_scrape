"""Tests for the new CLI push subcommand and --analyse / --push-notion flags on search."""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from apt_scrape.cli import cli


ENVELOPE = {
    "count": 1,
    "city": "milano",
    "area": "bicocca",
    "source": "Immobiliare.it",
    "listings": [
        {
            "title": "Bilocale",
            "url": "https://www.immobiliare.it/annunci/99/",
            "price": "€ 900/mese",
            "sqm": "55 m²",
            "rooms": "2 locali",
            "address": "Bicocca",
            "source": "Immobiliare.it",
        }
    ],
}


def _write_json(tmp_path, data):
    p = tmp_path / "result.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_push_subcommand_exists():
    """The 'push' subcommand is registered on the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli, ["push", "--help"])
    assert result.exit_code == 0
    assert "push" in result.output.lower() or "json" in result.output.lower()


def test_push_injects_area_and_city_into_listings(tmp_path):
    """push subcommand stamps _area and _city onto each listing before processing."""
    json_path = _write_json(tmp_path, ENVELOPE)

    # Because analysis and notion_push are lazy-imported inside _run_push,
    # we patch their module-level symbols directly.
    with patch("apt_scrape.analysis.analyse_listings", new_callable=AsyncMock) as mock_analyse, \
         patch("apt_scrape.notion_push.push_listings", new_callable=AsyncMock) as mock_push, \
         patch("apt_scrape.analysis.load_preferences", return_value="I want a nice place."):

        runner = CliRunner()
        runner.invoke(cli, ["push", json_path, "--analyse", "--push-notion"],
                      env={
                          "OPENROUTER_API_KEY": "fake",
                          "NOTION_API_KEY": "fake",
                          "NOTION_APARTMENTS_DB_ID": "fake-db-id",
                      })

    call_args = mock_analyse.call_args
    listings_passed = call_args[0][0] if call_args else []
    for listing in listings_passed:
        assert listing.get("_area") == "bicocca"
        assert listing.get("_city") == "milano"


def test_push_writes_updated_json_atomically(tmp_path):
    """push subcommand writes back updated JSON (with ai_* fields) to the original file."""
    envelope = dict(ENVELOPE)
    json_path = _write_json(tmp_path, envelope)

    async def fake_analyse(listings, preferences):
        for l in listings:
            l["ai_score"] = 75
            l["ai_stars"] = "⭐⭐⭐⭐"
            l["ai_verdict"] = "Good"
            l["ai_reason"] = "Nice place."

    with patch("apt_scrape.analysis.analyse_listings", side_effect=fake_analyse), \
         patch("apt_scrape.analysis.load_preferences", return_value="I want a nice place."):

        runner = CliRunner()
        runner.invoke(cli, ["push", json_path, "--analyse"],
                      env={"OPENROUTER_API_KEY": "fake"})

    updated = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert updated["listings"][0]["ai_score"] == 75
    assert updated["listings"][0]["ai_stars"] == "⭐⭐⭐⭐"


def test_search_command_accepts_analyse_flag():
    """--analyse flag is a valid option on the search command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "--help"])
    assert "--analyse" in result.output


def test_search_command_accepts_push_notion_flag():
    """--push-notion flag is a valid option on the search command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "--help"])
    assert "--push-notion" in result.output
