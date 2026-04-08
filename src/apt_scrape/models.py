"""apt_scrape.models — Pydantic v2 models for validated listing data.

These replace the dataclass-based ListingSummary/ListingDetail from
sites.base with proper validation, normalization, and serialization.
The dataclasses in sites.base remain as internal parser output types;
these models are the canonical data representation used by the pipeline,
storage, and export layers.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from pydantic import BaseModel, Field, field_validator


# Tracking params to strip from listing URLs
_STRIP_PARAMS = {"ref", "utm_source", "utm_medium", "utm_campaign", "utm_content", "fbclid"}


def _clean_url(url: str) -> str:
    """Strip tracking query params from a URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k not in _STRIP_PARAMS}
    return urlunparse(parsed._replace(query=urlencode(cleaned, doseq=True)))


def _extract_price(price_str: str) -> float | None:
    """Extract numeric price from Italian price strings.

    Examples:
        '€ 1.200/mese' → 1200.0
        '€ 250.000' → 250000.0
        '1200 €' → 1200.0
    """
    if not price_str:
        return None
    # Remove currency symbols, /mese, /anno, whitespace
    cleaned = re.sub(r'[€$£]', '', price_str)
    cleaned = re.sub(r'/(mese|anno|month|year)', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    # Italian format: 1.200 (thousands separator is dot)
    match = re.search(r'[\d.]+', cleaned)
    if not match:
        return None
    num_str = match.group()
    # If pattern is like 1.200 or 250.000 (dot as thousands sep)
    parts = num_str.split('.')
    if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
        # Dot is thousands separator
        return float(num_str.replace('.', ''))
    # Otherwise treat dot as decimal
    return float(num_str)


class ListingSummaryModel(BaseModel):
    """Validated listing summary from search results."""

    source: str
    title: str = ""
    url: str
    price: str = ""
    price_numeric: float | None = None
    sqm: str = ""
    rooms: str = ""
    bathrooms: str = ""
    address: str = ""
    thumbnail: str = ""
    description_snippet: str = ""
    post_date: str = ""
    raw_features: list[str] = Field(default_factory=list)

    # Pipeline metadata (stamped during processing)
    area: str = ""
    city: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("URL must not be empty")
        return _clean_url(v.strip())

    def extract_price_numeric(self) -> float | None:
        """Extract numeric price from the price string."""
        return _extract_price(self.price)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, compatible with existing code."""
        return self.model_dump()

    @classmethod
    def from_legacy_dict(cls, d: dict[str, Any]) -> "ListingSummaryModel":
        """Create from a legacy dict (as produced by old dataclass.to_dict())."""
        return cls(
            source=d.get("source", ""),
            title=d.get("title", ""),
            url=d.get("url", ""),
            price=d.get("price", ""),
            sqm=d.get("sqm", ""),
            rooms=d.get("rooms", ""),
            bathrooms=d.get("bathrooms", ""),
            address=d.get("address", ""),
            thumbnail=d.get("thumbnail", ""),
            description_snippet=d.get("description_snippet", ""),
            post_date=d.get("post_date", ""),
            raw_features=d.get("raw_features", []),
            area=d.get("_area", d.get("area", "")),
            city=d.get("_city", d.get("city", "")),
        )


class ListingDetailModel(BaseModel):
    """Validated listing detail from a detail page."""

    source: str
    url: str
    title: str = ""
    price: str = ""
    description: str = ""
    address: str = ""
    size: str = ""
    floor: str = ""
    extra_info: dict[str, str] = Field(default_factory=dict)
    photos: list[str] = Field(default_factory=list)
    energy_class: str = ""
    agency: str = ""
    post_date: str = ""
    costs: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("photos")
    @classmethod
    def cap_photos(cls, v: list[str]) -> list[str]:
        return v[:20]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_legacy_dict(cls, d: dict[str, Any]) -> "ListingDetailModel":
        return cls(**{k: v for k, v in d.items() if k in cls.model_fields})
