import pytest
from apt_scrape.models import ListingSummaryModel, ListingDetailModel


def test_listing_summary_valid():
    ls = ListingSummaryModel(
        source="Immobiliare.it",
        title="Bilocale via Roma",
        url="https://www.immobiliare.it/annunci/123/",
        price="€ 1.200/mese",
    )
    assert ls.source == "Immobiliare.it"
    assert ls.price_numeric is None  # not extracted yet


def test_listing_summary_price_extraction():
    ls = ListingSummaryModel(
        source="test",
        title="Test",
        url="https://example.com/1",
        price="€ 1.200/mese",
    )
    assert ls.extract_price_numeric() == 1200.0


def test_listing_summary_price_extraction_vendita():
    ls = ListingSummaryModel(
        source="test",
        title="Test",
        url="https://example.com/1",
        price="€ 250.000",
    )
    assert ls.extract_price_numeric() == 250000.0


def test_listing_summary_rejects_empty_url():
    with pytest.raises(ValueError):
        ListingSummaryModel(source="test", title="Test", url="")


def test_listing_summary_normalizes_url():
    ls = ListingSummaryModel(
        source="test",
        title="Test",
        url="https://www.immobiliare.it/annunci/123/?ref=search",
    )
    # Strip tracking params
    assert "ref=" not in ls.url


def test_listing_detail_valid():
    ld = ListingDetailModel(
        source="Immobiliare.it",
        url="https://www.immobiliare.it/annunci/123/",
        title="Bilocale via Roma",
        price="€ 1.200/mese",
        description="Appartamento luminoso...",
    )
    assert ld.source == "Immobiliare.it"


def test_listing_detail_photos_capped():
    ld = ListingDetailModel(
        source="test",
        url="https://example.com/1",
        photos=[f"https://img.com/{i}.jpg" for i in range(30)],
    )
    assert len(ld.photos) == 20


def test_listing_summary_to_dict_roundtrip():
    ls = ListingSummaryModel(
        source="test",
        title="Test",
        url="https://example.com/1",
        price="€ 900/mese",
        sqm="65 m²",
        rooms="3 locali",
    )
    d = ls.to_dict()
    assert d["source"] == "test"
    assert d["sqm"] == "65 m²"
    assert isinstance(d, dict)
